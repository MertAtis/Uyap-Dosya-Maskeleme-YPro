# -*- coding: utf-8 -*-
"""
Ayrıntılı sentetik UYAP dava senaryosu testleri.

Bu dosya yalnızca test üretir ve maskeleme motorunun (UyapRedactor) mevcut
davranışını sözleşmeye göre ölçer; motor dosyalarına dokunmaz.
Tüm kişi adları, TCKN, IBAN, telefon, adres ve kurum numaraları tamamen uydurmadır.
"""

from __future__ import annotations

import difflib
import json
import os
import re
import tempfile
import unittest
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from uyap_redactor import UyapRedactor


# ---------------------------------------------------------------------------
# Sentetik veri üreteçleri (algoritmik geçerlilik, sıfır gerçek veri)
# ---------------------------------------------------------------------------

def _make_tckn(seed9: str) -> str:
    """9 haneli tohumdan algoritmik olarak geçerli 11 haneli TCKN üretir."""
    assert len(seed9) == 9 and seed9.isdigit() and seed9[0] != "0", seed9
    d = [int(c) for c in seed9]
    odd = d[0] + d[2] + d[4] + d[6] + d[8]
    even = d[1] + d[3] + d[5] + d[7]
    d10 = (odd * 7 - even) % 10
    d11 = (sum(d) + d10) % 10
    return f"{seed9}{d10}{d11}"


def _make_non_tckn(seed9: str) -> str:
    """TCKN sağlama toplamını kasıtlı olarak bozan 11 haneli sahte barkod/evrak no."""
    valid = _make_tckn(seed9)
    last = (int(valid[-1]) + 3) % 10
    return valid[:-1] + str(last)


def _make_iban(bank_code5: str, account16: str) -> str:
    """Mod-97 sağlama toplamı geçerli sentetik TR IBAN üretir."""
    assert len(bank_code5) == 5 and bank_code5.isdigit()
    assert len(account16) == 16 and account16.isdigit()
    bban = f"{bank_code5}0{account16}"
    numeric = int(bban + "292700")  # T=29, R=27, 00
    check = 98 - (numeric % 97)
    return f"TR{check:02d}{bban}"


def _format_iban_groups(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def _make_card(prefix15: str) -> str:
    """Luhn sağlama toplamı geçerli sentetik 16 haneli kart numarası üretir."""
    assert len(prefix15) == 15 and prefix15.isdigit()
    digits = [int(c) for c in prefix15]
    total = 0
    for idx, val in enumerate(reversed(digits)):
        if idx % 2 == 0:
            val *= 2
            if val > 9:
                val -= 9
        total += val
    check = (10 - (total % 10)) % 10
    return f"{prefix15}{check}"


def _tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def _tr_fold(s: str) -> str:
    s = _tr_lower(s)
    trans = str.maketrans("çğıöşüâîû", "cgiosuaiu")
    return " ".join(s.translate(trans).split())


_TAG_RE = re.compile(
    r"\[(?:TCKN|IBAN|KART|HESAP|TEL|SERİ_NO|MRZ|SİCİL|ADRES|"
    r"DAVACI|DAVALI|MÜŞTEKİ|ŞÜPHELİ|SANIK|KATILAN|MAĞDUR|TANIK|ALACAKLI|BORÇLU|ASÇ|HAKİM|SAVCI|KÂTİP|KİŞİ)_\d+\]"
)


@dataclass
class Senaryo:
    ad: str
    baslik: str
    dosyalar: Dict[str, str]
    gizli: List[str]
    korunan: List[str]
    kisiler: Dict[str, str]  # {"Ad Soyad": "ROL_ONEKI"}
    ayni_etiket: List[List[str]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Senaryo 1: Çekişmeli Boşanma
# ---------------------------------------------------------------------------
def _build_senaryo_01() -> Senaryo:
    tc_davaci = _make_tckn("104829315")
    tc_davali = _make_tckn("209481726")
    tc_tanik = _make_tckn("318274659")
    tc_cocuk = _make_tckn("501928374")
    iban_davaci = _make_iban("00010", "0048291038472615")
    iban_davaci_grp = _format_iban_groups(iban_davaci)

    dava_dilekcesi = f"""# ANKARA 4. AİLE MAHKEMESİ SAYIN HAKİMLİĞİNE

**DOSYA NO:** 2025/418 E.
**TARİH:** 12.02.2025

**DAVACI:** Zeynep Aktaş (T.C. Kimlik No: {tc_davaci})
**ADRESİ:** Papatya Sokak No: 18/4 Yenimahalle/Ankara
**CEP TELEFONU:** 0532 411 22 33
**VEKİLİ:** Av. Selin Korkmaz (Ankara Barosu)

**DAVALI:** Burak Aktaş (T.C. Kimlik No: {tc_davali})
**ADRESİ:** Ihlamur Caddesi No: 42 Daire: 7 Keçiören/Ankara
**CEP TELEFONU:** 0544 822 19 05

**KONU:** TMK m. 166/1 uyarınca evlilik birliğinin temelinden sarsılması nedeniyle
çekişmeli boşanma, müşterek çocuğun velayeti, iştirak ve yoksulluk nafakası talebidir.

## AÇIKLAMALAR

1. Davacı müvekkil Zeynep Aktaş ile davalı Burak Aktaş 18.06.2016 tarihinde evlenmiştir.
Müvekkilin doğum tarihi 14.05.1988, Baba adı: Hasan, Anne adı: Fatma olup evlilikten
Mert Can Aktaş (T.C. Kimlik No: {tc_cocuk}) isminde bir müşterek çocukları dünyaya gelmiştir.

2. Taraflar arasındaki şiddetli geçimsizlik son iki yılda artmış; davalı ortak konutu
sık sık terk etmiş, evin temel ihtiyaçlarını karşılamaktan kaçınmıştır. Bu husus
komşu tanık Elif Demir beyanlarıyla da sabit olacaktır.

3. Müşterek çocuk Mert halen ilkokul öğrencisi olup annesi Zeynep Aktaş ile birlikte
yaşamaktadır. Çocuğun üstün yararı gereği velayetin anneye verilmesi zorunludur.

4. Nafaka ödemelerinin yapılabilmesi için müvekkile ait banka hesabı aşağıdadır:
   Hesap Sahibi: ZEYNEP AKTAŞ
   IBAN: {iban_davaci}
   İrtibat GSM: +90 532 411 22 33

5. Sosyal inceleme sırasında okul ve ikamet çevresi değerlendirilecek, aylık
7.500,00 TL iştirak nafakası ile 5.000,00 TL yoksulluk nafakasına hükmedilmesi talep
edilmektedir.

## HUKUKİ NEDENLER
TMK m. 166, m. 169, m. 175, m. 182 ve HMK ilgili hükümleri.

## DELİLLER
1. Nüfus kayıt örneği ve sosyal inceleme raporu,
2. Tanık Elif Demir (Tel: 0535 601 77 88) beyanı,
3. Gelir durumu araştırması ve banka kayıtları.

## SONUÇ VE İSTEM
Yukarıda açıklanan nedenlerle tarafların boşanmalarına, müşterek çocuk Mert Can Aktaş
velayetinin davacı Zeynep Aktaş'a verilmesine karar verilmesini arz ve talep ederim.

Davacı Vekili
Av. Selin Korkmaz
"""

    cevap_dilekcesi = f"""# ANKARA 4. AİLE MAHKEMESİNE

**ESAS NO:** 2025/418 E.
**TARİH:** 03.03.2025

**CEVAP VEREN DAVALI:** Burak Aktaş (TCKN: {tc_davali})
**ADRES:** Ihlamur Caddesi No: 42 Daire: 7 Keçiören/Ankara
**VEKİLİ:** Av. Tarık Şahin

**DAVACI:** Zeynep Aktaş (TCKN: {tc_davaci})
**VEKİLİ:** Av. Selin Korkmaz

**KONU:** Davaya karşı cevaplarımızın ve karşı taleplerimizin sunulmasıdır.

## AÇIKLAMALAR

1. Davacı Zeynep Aktaş tarafından ikame edilen boşanma davasındaki kusur atıfları
gerçeği yansıtmamaktadır. Davalı müvekkil Burak Aktaş evlilik birliğinin yüklediği
sorumlulukları düzenli şekilde yerine getirmiştir.

2. Davacının iddia ettiği olaylar çarpıtılmış olup taraflar arasındaki tartışmalar
üçüncü kişilerin aile içine müdahalesinden kaynaklanmıştır.

3. Müşterek çocuk Mert Can Aktaş üzerindeki velayet değerlendirmesinde her iki
ebeveynin yaşam koşulları eşit biçimde incelenmelidir. Müvekkilin ikamet ettiği
Keçiören/Ankara adresinde çocuk için ayrı oda hazırlanmıştır.

4. Talep edilen 7.500,00 TL iştirak nafakası davalının mevcut maaş geliriyle
orantısızdır. Ayrıca davacı adına kayıtlı {iban_davaci_grp} numaralı hesapta
düzenli kira geliri bulunduğu banka müzekkeresi ile ortaya çıkacaktır.

5. Davalı iletişim numarası 05448221905 olup tebligatların yukarıdaki vekil
adresine yapılması rica olunur.

## DELİLLER
1. SGK hizmet dökümü ve maaş bordroları,
2. Tanık beyanları,
3. Banka hesap ekstreleri ve nüfus kayıtları.

## SONUÇ VE İSTEM
Haksız davanın reddine, yargılama giderleri ile vekâlet ücretinin davacı tarafa
yükletilmesine karar verilmesini vekâleten arz ve talep ederim.

Davalı Vekili
Av. Tarık Şahin
"""

    tensip_zapti = f"""# T.C. ANKARA 4. AİLE MAHKEMESİ
## TENSİP ZAPTI

**ESAS NO:** 2025/418 E.
**HAKİM:** Hâkim Nermin Güler
**KATİP:** Zabıt Kâtibi Onur Yüksel
**TARİH:** 05.03.2025

**DAVACI:** Zeynep Aktaş - T.C. No: {tc_davaci}
**VEKİLİ:** Av. Selin Korkmaz
**DAVALI:** Burak Aktaş - T.C. No: {tc_davali}
**VEKİLİ:** Av. Tarık Şahin

Dava dilekçesi ile cevap dilekçesi incelendi, gereği düşünüldü:

1. Yargılamanın yazılı yargılama usulüne göre yürütülmesine,
2. Harç ve gider avansının eksiksiz yatırıldığının tespitine,
3. Davacı Zeynep Aktaş ile davalı Burak Aktaş'ın sosyal ve ekonomik durumlarının
   tespiti için ilgili kolluk birimlerine müzekkere yazılmasına,
4. Müşterek çocuk Mert Can Aktaş (TCKN: {tc_cocuk}) hakkında TMK m. 182 uyarınca
   Çankaya Sosyal Hizmet Merkezi uzmanından sosyal inceleme raporu alınmasına,
5. Davacı tarafın bildirdiği tanık Elif Demir için duruşma davetiyesi çıkarılmasına,
6. Davacıya ait {iban_davaci} IBAN numaralı hesabın son bir yıllık dökümünün
   ilgili bankadan celbine,
7. Tarafların MERNİS adreslerinin UYAP üzerinden sorgulanarak dosyaya alınmasına,
8. Mahkeme kalemi irtibat hattının 0312 222 33 44 olarak taraflara bildirilmesine,
9. Ön inceleme duruşmasının 15.05.2025 günü saat 10:15'e bırakılmasına karar verildi.

Taraf iletişim kayıtları:
- Davacı Cep: 05324112233
- Davalı Cep: 0544 822 19 05
- Davacı Adres: Papatya Sokak No: 18/4 Yenimahalle/Ankara
- Davalı Adres: Ihlamur Caddesi No: 42 Daire: 7 Keçiören/Ankara

İşbu tensip zaptı elektronik imza ile düzenlenmiştir.
Duruşma günü taraflara elektronik tebligat yoluyla bildirilecektir.
Taraf vekillerinin duruşmadan en az iki hafta önce varsa eksik delillerini sunmaları ihtar olunur.
Tensip zaptının bir sureti UYAP vatandaş portalına yüklenmiştir.

Hâkim Nermin Güler
Zabıt Kâtibi Onur Yüksel
"""

    sir_raporu = f"""# SOSYAL İNCELEME RAPORU

**MAHKEME:** Ankara 4. Aile Mahkemesi
**DOSYA NO:** 2025/418 E.
**RAPORU DÜZENLEYEN:** Sosyal Çalışmacı Hülya Arslan
**KURUM:** Çankaya Sosyal Hizmet Merkezi
**TARİH:** 18.04.2025

## 1. GÖRÜŞME YAPILAN KİŞİLER
- **Anne (Davacı):** Zeynep Aktaş (TCKN: {tc_davaci}, Tel: 0532 411 22 33)
- **Baba (Davalı):** Burak Aktaş (TCKN: {tc_davali}, Tel: 0544 822 19 05)
- **Müşterek Çocuk:** Mert Can Aktaş (TCKN: {tc_cocuk})

## 2. EV ZİYARETİ VE GÖZLEMLER
10.04.2025 tarihinde anne Zeynep Aktaş'ın ikamet ettiği Papatya Sokak No: 18/4
Yenimahalle/Ankara adresine ev ziyareti gerçekleştirilmiştir. Konutun üç odalı,
aydınlık, hijyenik ve küçük Mert'in eğitim gelişimine uygun olduğu görülmüştür.

12.04.2025 tarihinde baba Burak Aktaş ile Ihlamur Caddesi No: 42 Daire: 7
Keçiören/Ankara adresinde görüşülmüştür. Baba çalışma saatlerinin yoğun olduğunu,
çocuğun bakımında babaanneden destek alabileceğini ifade etmiştir.

## 3. ÇOCUKLA YAPILAN GÖRÜŞME
Mert Can Aktaş ile yalnız yapılan görüşmede çocuğun annesinin yanında kendini güvende
hissettiği, okul çevresini sevdiği, ancak babasıyla da hafta sonları düzenli olarak
görüşmek istediği gözlemlenmiştir. Çocuğun mevcut okul düzeninin bozulmaması
psikososyal gelişimi açısından önem arz etmektedir.

## 4. KANAAT VE ÖNERİ
Müşterek çocuğun yaş, eğitim ve duygusal bağ durumu dikkate alındığında geçici ve nihai
velayetin anne Zeynep Aktaş'a bırakılması, baba Burak Aktaş ile her ayın 1. ve 3.
hafta sonları yatılı kişisel ilişki kurulması uygun mütalaa edilmiştir.

Saygılarımla arz ederim.

## EKLER
1. Görüşme tutanakları ve ev gözlem formu,
2. Okul rehberlik servisi bilgilendirme notu.

Sosyal Çalışmacı Hülya Arslan
Çankaya Sosyal Hizmet Merkezi
Rapor Teslim Tarihi: 18.04.2025
"""

    tanik_beyan = f"""# TANIK BEYAN TUTANAĞI

**MAHKEME:** Ankara 4. Aile Mahkemesi
**DOSYA NO:** 2025/418 E.
**DURUŞMA TARİHİ:** 15.05.2025
**SAAT:** 10:30
**HAKİM:** Hâkim Nermin Güler
**ZABIT KATİBİ:** Zabıt Kâtibi Onur Yüksel

**TANIK:** Elif Demir (T.C. Kimlik No: {tc_tanik})
**TELEFON:** 0535 601 77 88
**ADRES:** Papatya Sokak No: 20/2 Yenimahalle/Ankara

Tanığa usulüne uygun yemini yaptırıldı, kimliği tespit edildi. Davacı Zeynep Aktaş'ın
aynı apartmanda alt komşusu, davalı Burak Aktaş'ı da evlilik süresince tanıdığını
belirtti. Tanıklığa engel hali bulunmadığı anlaşıldı, HMK m. 259 uyarınca ihtarat
yapıldı.

## TANIK BEYANI
"Ben yaklaşık dört yıldır davacı Zeynep Aktaş ile aynı binada oturmaktayım. Davalı
Burak Aktaş son iki senedir eve çok geç saatlerde gelir, çoğu hafta sonu evde
bulunmazdı. Zeynep hem evin tüm işlerini hem de küçük çocuğun okul masraflarını
tek başına üstlenmeye çalışıyordu. Birkaç kez yüksek sesli tartışmalarına apartman
boşluğundan şahit oldum. Çocuk genelde annesiyle parkta vakit geçirirdi. Bildiklerim
bundan ibarettir."

Beyanı sesli olarak okundu, doğruluğu tanık tarafından onaylandı ve imzası alındı.

Tanık
Elif Demir

Davacı Vekili: Av. Selin Korkmaz - "Tanık beyanlarını kabul ediyoruz, aleyhe
husus bulunmamaktadır."
Davalı Vekili: Av. Tarık Şahin - "Aleyhe hususları kabul etmiyoruz, tanık
beyanına karşı yazılı beyanda bulunacağız."

Duruşma zaptı mahkeme huzurunda okunarak taraf vekillerine elektronik ortamda tebliğ edildi.
Bir sonraki celse için tahkikat aşamasına geçilmesine karar verildi.

Hâkim Nermin Güler
Zabıt Kâtibi Onur Yüksel
"""

    project_json = json.dumps(
        {
            "dosyaNo": "2025/418 E.",
            "mahkeme": "Ankara 4. Aile Mahkemesi",
            "taraflar": [
                {"sifat": "Davacı", "adSoyad": "Zeynep Aktaş", "tckn": tc_davaci, "telefon": "0532 411 22 33"},
                {"sifat": "Davalı", "adSoyad": "Burak Aktaş", "tckn": tc_davali, "telefon": "0544 822 19 05"},
                {"sifat": "Tanık", "adSoyad": "Elif Demir", "tckn": tc_tanik},
                {"sifat": "Vekil", "adSoyad": "Av. Selin Korkmaz"},
                {"sifat": "Vekil", "adSoyad": "Av. Tarık Şahin"},
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    return Senaryo(
        ad="01_cekismeli_bosanma",
        baslik="Çekişmeli Boşanma (Velayet, Nafaka, SIR)",
        dosyalar={
            "01_Dava_Dilekcesi.md": dava_dilekcesi,
            "02_Cevap_Dilekcesi.md": cevap_dilekcesi,
            "03_Tensip_Zapti.md": tensip_zapti,
            "Ekler/Sosyal_Inceleme_Raporu.md": sir_raporu,
            "Ekler/Tanik_Elif_Demir_Beyan_Tutanagi.md": tanik_beyan,
            "uyap-project.json": project_json,
        },
        gizli=[
            tc_davaci, tc_davali, tc_tanik, tc_cocuk,
            "0532 411 22 33", "05324112233", "+90 532 411 22 33",
            "0544 822 19 05", "05448221905", "0535 601 77 88",
            iban_davaci, iban_davaci_grp,
            "Papatya Sokak No: 18/4", "Ihlamur Caddesi No: 42 Daire: 7", "Papatya Sokak No: 20/2",
            "Zeynep Aktaş", "Burak Aktaş", "Elif Demir", "Mert Can Aktaş",
            "Elif_Demir", "Nermin Güler", "Onur Yüksel",
        ],
        korunan=[
            "Av. Selin Korkmaz", "Av. Tarık Şahin",
            "Sosyal Çalışmacı Hülya Arslan",
            "Ankara 4. Aile Mahkemesi", "Çankaya Sosyal Hizmet Merkezi",
            "Baba adı: Hasan", "Anne adı: Fatma", "14.05.1988",
            "7.500,00 TL", "2025/418 E.", "TMK m. 166", "0312 222 33 44",
            "Yenimahalle/Ankara", "Keçiören/Ankara",
        ],
        kisiler={
            "Zeynep Aktaş": "DAVACI",
            "Burak Aktaş": "DAVALI",
            "Elif Demir": "TANIK",
            "Mert Can Aktaş": "KİŞİ",
            "Nermin Güler": "HAKİM",
            "Onur Yüksel": "KÂTİP",
        },
        ayni_etiket=[
            [tc_davaci],
            ["0532 411 22 33", "+90 532 411 22 33", "05324112233"],
            [iban_davaci, iban_davaci_grp],
            ["Zeynep Aktaş", "ZEYNEP AKTAŞ"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 2: İşe İade / İşçilik Alacağı
# ---------------------------------------------------------------------------
def _build_senaryo_02() -> Senaryo:
    tc_davaci = _make_tckn("152938471")
    tc_yetkili = _make_tckn("263849510")
    tc_tanik = _make_tckn("374950612")
    iban_davaci = _make_iban("00062", "0019283746550123")
    hesap_no = "48291047"

    arabuluculuk = f"""# ARABULUCULUK SON TUTANAĞI

**ARABULUCULUK BÜROSU:** İstanbul Anadolu Arabuluculuk Bürosu
**DOSYA NO:** 2025/11240 ARB
**ARABULUCU:** Arabulucu Av. Deniz Çetin (Sicil: 19283)
**TARİH:** 10.01.2025

**BAŞVURUCU (İŞÇİ):** Kemal Özkan (TCKN: {tc_davaci})
**ADRES:** Menekşe Sokak No: 12/5 Kartal/İstanbul
**CEP TEL:** 0533 712 45 89
**VEKİLİ:** Av. Emre Yalçın

**KARŞI TARAF (İŞVEREN):** Anadolu Lojistik Taşımacılık A.Ş.
**MERKEZ ADRESİ:** İkitelli Organize Sanayi Bölgesi 14. Cadde No: 8 Başakşehir/İstanbul
**ŞİRKET YETKİLİSİ:** Hakan Yıldırım (TCKN: {tc_yetkili})
**VEKİLİ:** Av. Nilay Arıkan

## MÜZAKERE KONUSU VE SÜREÇ
Başvurucu Kemal Özkan tarafından 4857 sayılı İş Kanunu kapsamında kıdem
tazminatı, ihbar tazminatı, fazla çalışma ücreti, yıllık izin ücreti ve işe
iade talepleri ile arabuluculuk başvurusunda bulunulmuştur.

Taraflar 27.12.2024 tarihli ilk oturum ile 10.01.2025 tarihli son oturumda
telekonferans ve yüz yüze görüşme yoluyla bir araya gelmişlerdir. İşçi vekili
Av. Emre Yalçın taleplerini toplam 68.450,00 TL olarak iletmiş; işveren temsilcisi
Hakan Yıldırım ise feshin geçerli nedene dayandığını savunarak ödeme teklifini
reddetmiştir.

## SONUÇ
Yapılan müzakereler neticesinde taraflar uyuşmazlık konularının tamamında
ANLAŞAMAMIŞLARDIR.

İşbu son tutanak 6325 sayılı Hukuk Uyuşmazlıklarında Arabuluculuk Kanunu m. 18/A
uyarınca üç nüsha halinde düzenlenerek taraflar ve arabulucu tarafından imza
altına alınmıştır.

Arabulucu Av. Deniz Çetin
Başvurucu: Kemal Özkan
Başvurucu Vekili: Av. Emre Yalçın
Karşı Taraf Yetkilisi: Hakan Yıldırım
Karşı Taraf Vekili: Av. Nilay Arıkan
"""

    dava_dilekcesi = f"""# İSTANBUL ANADOLU 12. İŞ MAHKEMESİNE

**DOSYA NO:** 2025/112 E.
**TARİH:** 24.01.2025

**DAVACI:** Kemal Özkan (T.C. Kimlik No: {tc_davaci})
**ADRESİ:** Menekşe Sokak No: 12/5 Kartal/İstanbul
**TELEFON:** 05337124589
**VEKİLİ:** Av. Emre Yalçın

**DAVALI:** Anadolu Lojistik Taşımacılık A.Ş.
**ADRESİ:** İkitelli Organize Sanayi Bölgesi 14. Cadde No: 8 Başakşehir/İstanbul
**YETKİLİ:** Hakan Yıldırım
**VEKİLİ:** Av. Nilay Arıkan

**KONU:** 4857 sayılı İş Kanunu m. 18 vd. uyarınca feshin geçersizliğinin tespiti ile
işe iade ve 68.450,00 TL tutarında işçilik alacaklarının tahsili talebidir.

## AÇIKLAMALAR

1. Davacı müvekkil Kemal Özkan, davalı Anadolu Lojistik Taşımacılık A.Ş. bünyesinde
02.03.2020 - 15.12.2024 tarihleri arasında sevkiyat sorumlusu olarak çalışmıştır.

2. İş sözleşmesi şirket yetkilisi Hakan Yıldırım tarafından hiçbir savunma alınmadan
ve yazılı fesih bildirimi tebliğ edilmeden sonlandırılmıştır.

3. İşyerinde çalışan tanık Sema Tunç (TCKN: {tc_tanik}, Tel: 0542 309 88 77)
müvekkilin haftada altı gün günde on bir saat çalıştığına doğrudan şahittir.

4. Müvekkilin maaş ödemelerinin yatırıldığı banka bilgileri:
   IBAN: {iban_davaci}
   Müşteri / Hesap No: {hesap_no}

## DELİLLER
1. Arabuluculuk son tutanağı,
2. Kadıköy SGK Merkezi hizmet dökümü ve maaş bordroları,
3. Tanık Sema Tunç beyanı,
4. Bilirkişi incelemesi.

## SONUÇ VE İSTEM
Davanın kabulüne, feshin geçersizliğine ve müvekkilin işe iadesine karar
verilmesini vekâleten arz ederim.

Davacı Vekili
Av. Emre Yalçın
"""

    sgk_bordro = f"""# KADIKÖY SGK MERKEZİ HİZMET DÖKÜMÜ VE İŞYERİ BORDRO ÖZETİ

**İLGİLİ MAHKEME:** İstanbul Anadolu 12. İş Mahkemesi
**ESAS NO:** 2025/112 E.
**TARİH:** 19.02.2025

## 1. SİGORTALI BİLGİLERİ
- **Adı Soyadı:** Kemal Özkan
- **T.C. Kimlik No:** {tc_davaci}
- **İkamet Adresi:** Menekşe Sokak No: 12/5 Kartal/İstanbul
- **İşveren Ünvanı:** Anadolu Lojistik Taşımacılık A.Ş.
- **İşyeri Adresi:** İkitelli Organize Sanayi Bölgesi 14. Cadde No: 8 Başakşehir/İstanbul

## 2. ÖDEME VE BORDRO KAYITLARI
- İşe Giriş Tarihi: 02.03.2020
- İşten Ayrılış Tarihi: 15.12.2024
- Çıkış Kodu: 04 - Belirsiz süreli iş sözleşmesinin işveren tarafından haklı sebep
  bildirilmeden feshi
- Son Brüt Ücret: 38.500,00 TL
- Ödeme Hesap No: {hesap_no}
- Maaş IBAN: {iban_davaci}

## 3. AYLIK PRİM GÜN CETVELİ
| Dönem | Prim Gün | SPEK Tutarı | Ödeme Kanalı |
|---|---:|---:|---|
| 2024/07 | 30 | 38.500,00 TL | Banka Hesap {hesap_no} |
| 2024/08 | 30 | 38.500,00 TL | Banka Hesap {hesap_no} |
| 2024/09 | 30 | 38.500,00 TL | Banka Hesap {hesap_no} |
| 2024/10 | 30 | 38.500,00 TL | Banka Hesap {hesap_no} |
| 2024/11 | 30 | 38.500,00 TL | Banka Hesap {hesap_no} |
| 2024/12 | 15 | 19.250,00 TL | Banka Hesap {hesap_no} |

## 4. RESMİ ONAY
İşbu hizmet dökümü İstanbul Anadolu 12. İş Mahkemesi talebi üzerine
Kadıköy SGK Merkezi kayıtlarından çıkartılmıştır.
Kurum Sabit Telefon: 0216 414 22 00
Belge Doğrulama Kodu: SGK-2025-994120
Kurum KEP Adresi: kadikoysgk@hs01.kep.tr
Sayfa: 1 / 1
Düzenleyen: SGK Memuru Ayşe Yılmaz
Onay Tarihi: 19.02.2025
"""

    bilirkisi_raporu = f"""# BİLİRKİŞİ HESAPLAMA RAPORU

**MAHKEME:** İstanbul Anadolu 12. İş Mahkemesi
**DOSYA NO:** 2025/112 E.
**BİLİRKİŞİ:** Bilirkişi SMMM Mustafa Kara
**TARİH:** 14.04.2025

**DAVACI:** Kemal Özkan (TCKN: {tc_davaci})
**VEKİLİ:** Av. Emre Yalçın
**DAVALI:** Anadolu Lojistik Taşımacılık A.Ş.
**VEKİLİ:** Av. Nilay Arıkan

## 1. DOSYA İNCELEMESİ
Mahkemenizce tevdi olunan dosya kapsamında davacı Kemal Özkan'ın hizmet süresi,
Kadıköy SGK Merkezi kayıtları, banka dekontları ve tanık Sema Tunç (TCKN: {tc_tanik})
beyanları ayrıntılı biçimde incelenmiştir.

## 2. ÇALIŞMA SÜRESİ VE ÜCRET TESPİTİ
Davacının 02.03.2020 - 15.12.2024 tarihleri arasında 4 yıl 9 ay 13 gün süreyle
çalıştığı, son aylık brüt ücretinin 38.500,00 TL olduğu puantaj ve bordrolardan
tespit edilmiştir.

## 3. HESAPLAMA ÖZETİ
4857 sayılı İş Kanunu hükümleri çerçevesinde yapılan hesaplamada:
- Fazla mesai alacağı: 42.100,00 TL
- Yıllık izin ücreti: 14.350,00 TL
- UBGT alacağı: 12.000,00 TL
- **Toplam talep değerlendirmesi:** 68.450,00 TL

Banka dökümlerinde işveren Anadolu Lojistik Taşımacılık A.Ş. tarafından davacının
{iban_davaci} IBAN numaralı ve {hesap_no} hesap numaralı hesabına düzenli maaş
ödemesi yapıldığı, ayrıca elden prim ödendiğine dair belge sunulmadığı tespit
edilmiştir.

## 4. SONUÇ
Nihai hukuki takdir Sayın Mahkemeye ait olmak üzere işbu rapor iki nüsha olarak düzenlenmiştir.
Raporun taraflara HMK m. 280 uyarınca tebliğine ve itiraz için iki haftalık kesin süre verilmesine ilişkin takdir mahkemeye aittir.

Bilirkişi SMMM Mustafa Kara
Teslim Tarihi: 14.04.2025
"""

    project_json = json.dumps(
        {
            "dosyaNo": "2025/112 E.",
            "mahkeme": "İstanbul Anadolu 12. İş Mahkemesi",
            "taraflar": [
                {"sifat": "Davacı", "adSoyad": "Kemal Özkan", "tckn": tc_davaci},
                {"sifat": "Davalı", "adSoyad": "Anadolu Lojistik Taşımacılık A.Ş.", "tur": "Tüzel Kişi"},
                {"sifat": "Şirket Yetkilisi", "adSoyad": "Hakan Yıldırım", "tckn": tc_yetkili},
                {"sifat": "Tanık", "adSoyad": "Sema Tunç", "tckn": tc_tanik},
                {"sifat": "Vekil", "adSoyad": "Av. Emre Yalçın"},
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    return Senaryo(
        ad="02_ise_iade_iscilik",
        baslik="İşe İade / İşçilik Alacağı",
        dosyalar={
            "01_Arabuluculuk_Son_Tutanagi.md": arabuluculuk,
            "02_Dava_Dilekcesi.md": dava_dilekcesi,
            "03_SGK_Hizmet_Dokumu_ve_Bordro.md": sgk_bordro,
            "04_Bilirkisi_Hesap_Raporu.md": bilirkisi_raporu,
            "uyap-project.json": project_json,
        },
        gizli=[
            tc_davaci, tc_yetkili, tc_tanik,
            iban_davaci, hesap_no,
            "0533 712 45 89", "05337124589", "0542 309 88 77",
            "Menekşe Sokak No: 12/5",
            "19283",
            "Kemal Özkan", "Hakan Yıldırım", "Sema Tunç",
        ],
        korunan=[
            "Anadolu Lojistik Taşımacılık A.Ş.",
            "Arabulucu Av. Deniz Çetin",
            "Bilirkişi SMMM Mustafa Kara",
            "Av. Emre Yalçın",
            "Av. Nilay Arıkan",
            "İstanbul Anadolu 12. İş Mahkemesi",
            "Kadıköy SGK Merkezi",
            "İkitelli Organize Sanayi Bölgesi 14. Cadde No: 8 Başakşehir/İstanbul",
            "4857 sayılı İş Kanunu",
            "68.450,00 TL",
            "2025/112 E.",
        ],
        kisiler={
            "Kemal Özkan": "DAVACI",
            "Hakan Yıldırım": "KİŞİ",
            "Sema Tunç": "TANIK",
        },
        ayni_etiket=[
            [tc_davaci],
            [iban_davaci],
            [hesap_no],
            ["0533 712 45 89", "05337124589"],
            ["Kemal Özkan"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 3: İlamsız İcra Takibi + İtirazın İptali
# ---------------------------------------------------------------------------
def _build_senaryo_03() -> Senaryo:
    tc_alacakli = _make_tckn("192837465")
    tc_borclu = _make_tckn("283746519")
    iban_alacakli = _make_iban("00015", "0099887766554433")

    odeme_emri = f"""# T.C. İSTANBUL 18. İCRA MÜDÜRLÜĞÜ
## İLAMSIZ TAKİPLERDE ÖDEME EMRİ (ÖRNEK NO: 7)

**TAKİP DOSYA NO:** 2024/8910 Esas
**TARİH:** 04.11.2024

**ALACAKLI:** Serdar Aydın (T.C. Kimlik No: {tc_alacakli})
**ADRESİ:** Gülbahar Sokak No: 9/2 Şişli/İstanbul
**CEP TEL:** 0532 800 11 22
**VEKİLİ:** Av. Gökhan Balcı

**BORÇLU:** Murat Kılıç (T.C. Kimlik No: {tc_borclu})
**ADRESİ:** Fıstıklı Cadde No: 31/1 Beşiktaş/İstanbul
**CEP TEL:** 0536 900 44 55

**ALACAK MİKTARI:** 145.000,00 TL Asıl Alacak + İşleyecek Yasal Faiz
**ALACAĞIN SEBEBİ:** 15.08.2024 tarihli yazılı borç ikrarı ve cari hesap bakiyesi.

## İHTAR
1. Yukarıda yazılı borç ile takip masraflarını işbu ödeme emrinin tebliğinden
   itibaren 7 gün içinde İstanbul 18. İcra Müdürlüğü veznesine veya alacaklı
   Serdar Aydın hesabına ödemeniz gerekmektedir.
2. Borca, faize veya imzaya itirazınız varsa tebliğden itibaren 7 gün içinde
   bizzat veya vekil aracılığıyla dairemize yazılı olarak bildirmeniz gerekir.
3. Süresi içinde itiraz edilmediği ve borç ödenmediği takdirde hakkınızda
   cebri icra ve haciz işlemlerinin uygulanacağı İİK m. 60 gereğince ihtar olunur.

## ÖDEME KANALLARI
- Ödeme IBAN: {iban_alacakli}
- İcra Dairesi Sabit Hat: 0212 310 45 00
- Vezne Çalışma Saatleri: 09:00 - 16:30

## TAKİP MASRAFLARI DÖKÜMÜ
- Başvurma Harcı: 427,60 TL
- Peşin Harç: 725,00 TL
- Tebligat Gideri: 210,00 TL
- Toplam Takip Çıkışı: 146.362,60 TL

İşbu ödeme emri UYAP üzerinden elektronik imzalı olarak düzenlenmiştir.

İcra Müdürü
Mehmet Demirtaş
"""

    itiraz_dilekcesi = f"""# İSTANBUL 18. İCRA MÜDÜRLÜĞÜNE

**DOSYA NO:** 2024/8910 Esas
**TARİH:** 12.11.2024

**İTİRAZ EDEN BORÇLU:** Murat Kılıç (TCKN: {tc_borclu})
**ADRES:** Fıstıklı Cadde No: 31/1 Beşiktaş/İstanbul
**TELEFON:** 05369004455

**ALACAKLI:** Serdar Aydın
**VEKİLİ:** Av. Gökhan Balcı

**KONU:** Ödeme emrine, borca, faize ve tüm fer'ilerine itirazımın sunulmasıdır.

## AÇIKLAMALAR
1. Tarafıma 08.11.2024 tarihinde tebliğ edilen İstanbul 18. İcra Müdürlüğü
   2024/8910 Esas sayılı ödeme emrine yasal 7 günlük süresi içinde açıkça itiraz ediyorum.

2. Alacaklı Serdar Aydın tarafından talep edilen 145.000,00 TL tutarındaki borç
   tarafımdan daha önce elden ve havale yoluyla ödenmiştir. Alacaklının {iban_alacakli}
   IBAN numaralı hesabına gönderilen dekontlar mevcuttur.

3. Alacaklının işlettiği faiz oranı ve takip masrafları da fahiş olup kabul
   edilmesi mümkün değildir. İcra takibi haksız ve kötüniyetlidir.

4. İİK m. 62 uyarınca borcun tamamına ve işlemiş faiz talebine itiraz ettiğimden
   hakkımdaki takibin durdurulmasına karar verilmesini arz ve talep ederim.

## EKLER
- Kimlik fotokopisi,
- Tebligat zarfı örneği,
- Banka havale dekontu suretleri.

## SONUÇ VE TALEP
Yukarıda açıklanan nedenlerle süresi içinde yapılan itirazımın kabulü ile
2024/8910 Esas sayılı icra takibinin İİK m. 66 gereğince durdurulmasına,
takip masraflarının alacaklı üzerinde bırakılmasına karar verilmesini arz ederim.

Borçlu
Murat Kılıç
Tarih: 12.11.2024
"""

    itirazin_iptali = f"""# İSTANBUL 22. ASLİYE HUKUK MAHKEMESİNE

**ESAS NO:** 2025/64 E.
**TARİH:** 09.01.2025

**DAVACI:** Serdar Aydın (T.C. Kimlik No: {tc_alacakli})
**ADRES:** Gülbahar Sokak No: 9/2 Şişli/İstanbul
**CEP TEL:** 0532 800 11 22
**VEKİLİ:** Av. Gökhan Balcı

**DAVALI:** Murat Kılıç (T.C. Kimlik No: {tc_borclu})
**ADRES:** Fıstıklı Cadde No: 31/1 Beşiktaş/İstanbul
**CEP TEL:** 0536 900 44 55

**KONU:** İstanbul 18. İcra Müdürlüğü 2024/8910 Esas sayılı dosyasına yapılan
haksız itirazın İİK m. 67 uyarınca iptali ile takibin devamı ve %20 icra inkâr
tazminatına hükmedilmesi talebidir.

## AÇIKLAMALAR
1. Davacı Serdar Aydın tarafından davalı Murat Kılıç aleyhine 145.000,00 TL alacağın
   tahsili amacıyla ilamsız icra takibi başlatılmıştır.

2. Davalı Murat Kılıç kötüniyetli olarak borca itiraz etmiş, herhangi bir ödeme
   dekontu ibraz edememiştir. Müvekkilin {iban_alacakli} numaralı hesabına herhangi bir
   borç kapatma ödemesi gelmemiştir.

3. İİK m. 67 uyarınca süresinde İstanbul 22. Asliye Hukuk Mahkemesi nezdinde açılan
   işbu itirazın iptali davasında itirazın tümden iptaline ve davalının %20 oranında
   icra inkâr tazminatına mahkûm edilmesine karar verilmesi gerekmektedir.

## HUKUKİ SEBEPLER VE DELİLLER
- İİK m. 67, HMK ve TBK ilgili maddeleri,
- İstanbul 18. İcra Müdürlüğü 2024/8910 Esas sayılı takip dosyası,
- 15.08.2024 tarihli yazılı borç ikrarı ve banka hesap kayıtları.

## SONUÇ VE İSTEM
Davamızın kabulü ile davalı Murat Kılıç'ın itirazının iptaline karar verilmesini
vekaleten arz ederim.

Davacı Vekili
Av. Gökhan Balcı
"""

    tebligat_cevap = f"""# İSTANBUL 22. ASLİYE HUKUK MAHKEMESİNE
## TEBLİGAT MAZBATASI VE CEVAP DİLEKÇESİ

**MAHKEME:** İstanbul 22. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/64 E.
**TARİH:** 05.02.2025

**TEBLİGAT ALAN DAVALI:** Murat Kılıç (TCKN: {tc_borclu})
**ADRES:** Fıstıklı Cadde No: 31/1 Beşiktaş/İstanbul
**TEBLİĞ TARİHİ:** 23.01.2025 - Muhataba bizzat teslim edildi.
**TEBLİĞ MEMURU:** PTT Dağıtıcısı Hasan Demir

**DAVACI:** Serdar Aydın (TCKN: {tc_alacakli})
**VEKİLİ:** Av. Gökhan Balcı

## CEVAP BEYANLARIMIZ
1. Davacı Serdar Aydın tarafından açılan itirazın iptali davasını kabul etmiyorum.
2. Davacı ile aramızdaki ticari ilişkiden doğan 145.000,00 TL bedel, sözleşme
   koşulları gereği mahsup edilmiştir; ekstreler mahkemeye sunulacaktır.
3. Davacının icra inkâr tazminatı talebi de yerinde değildir, zira alacak likit
   ve muayyen olmaktan uzaktır.
4. İstanbul 18. İcra Müdürlüğü 2024/8910 Esas sayılı takip haksız olduğundan
   davanın reddi ile davacı aleyhine %20 kötüniyet tazminatına hükmedilmesini talep
   ediyorum.

## DELİLLER
1. Banka havale dekontları,
2. Ticari yazışmalar ve tanık beyanları,
3. Cari hesap mutabakat kayıtları.

## SONUÇ VE TALEP
Davanın esastan reddi ile kötüniyet tazminatı ve yargılama giderlerinin
davacıya yükletilmesine karar verilmesini arz ederim.

İletişim Telefonu: 0536 900 44 55

Davalı
Murat Kılıç
Tarih: 05.02.2025
Ek: Ödeme dekontları ve tebligat zarfı
Sayfa 1 / 1
"""

    return Senaryo(
        ad="03_icra_itirazin_iptali",
        baslik="İlamsız İcra Takibi + İtirazın İptali",
        dosyalar={
            "01_Ilamsiz_Odeme_Emri_Ornek7.md": odeme_emri,
            "02_Borca_Itiraz_Dilekcesi.md": itiraz_dilekcesi,
            "03_Itirazin_Iptali_Dava_Dilekcesi.md": itirazin_iptali,
            "04_Tebligat_Mazbatasi_ve_Cevap.md": tebligat_cevap,
        },
        gizli=[
            tc_alacakli, tc_borclu, iban_alacakli,
            "0532 800 11 22", "0536 900 44 55", "05369004455",
            "Gülbahar Sokak No: 9/2", "Fıstıklı Cadde No: 31/1",
            "Serdar Aydın", "Murat Kılıç",
        ],
        korunan=[
            "İstanbul 18. İcra Müdürlüğü", "2024/8910 Esas",
            "İstanbul 22. Asliye Hukuk Mahkemesi", "2025/64 E.",
            "Av. Gökhan Balcı", "İİK m. 67", "145.000,00 TL", "0212 310 45 00",
        ],
        kisiler={
            "Serdar Aydın": "DAVACI",
            "Murat Kılıç": "DAVALI",
        },
        ayni_etiket=[
            ["Serdar Aydın"],
            ["Murat Kılıç"],
            [tc_borclu],
            [iban_alacakli],
            ["0536 900 44 55", "05369004455"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 4: Ceza — Kasten Yaralama
# ---------------------------------------------------------------------------
def _build_senaryo_04() -> Senaryo:
    tc_musteki = _make_tckn("147258369")
    tc_supheli = _make_tckn("258369147")
    tc_tanik = _make_tckn("369147258")

    kolluk_musteki = f"""# İZMİR İL EMNİYET MÜDÜRLÜĞÜ KONAK POLİS MERKEZİ AMİRLİĞİ
## MÜŞTEKİ İFADE TUTANAĞI

**SORUŞTURMA NO:** 2025/1402
**TARİH:** 05.01.2025 - SAAT: 22:15

**İFADEYİ ALAN GÖREVLİ:** Polis Memuru İbrahim Çelik (Sicil No: 348912)

**MÜŞTEKİ:** Cemre Doğan (T.C. Kimlik No: {tc_musteki})
**BABA ADI:** Kemal  **ANA ADI:** Sevgi  **DOĞUM TARİHİ:** 21.08.1992
**DOĞUM YERİ:** Konak / İzmir
**İKAMET ADRESİ:** Çınarlı Sokak No: 22/6 Konak/İzmir
**CEP TELEFONU:** 0530 112 33 44

## HAKLARIN HATIRLATILMASI
CMK m. 234 uyarınca müştekinin vekil seçme, delillerin toplanmasını isteme,
soruşturma dosyasından örnek alma ve uzlaşma hakkındaki yasal hakları
kendisine okunup açıklandı.

## İFADE
"Bugün saat 20:30 sıralarında Barış Parkı girişi önünde yürürken daha önceden
aracını park etmesi nedeniyle tartıştığım komşum Volkan Tekin ile karşılaştım.
Volkan Tekin bana hakaret ederek yüzüme yumruk attı ve sol kolumdan yaralandım.
Çevredeki vatandaşlar araya girerek bizi ayırdılar. Olay yerinde bulunan
Yusuf Karahan (Tel: 0537 889 10 20) olaya bizzat tanık oldu. Hastaneye gidip
darp raporu aldım. Volkan Tekin'den davacı ve şikâyetçiyim, uzlaşmak
istemiyorum."

Soruldu: Başka ekleyeceği bir husus olmadığını beyan etti.
İfade tutanağı okunup doğruluğu anlaşıldıktan sonra birlikte imza altına alındı.
Müştekiye adli muayeneye sevki için gerekli yazı elden teslim edildi.
Tutanak iki nüsha olarak düzenlendi, bir sureti müştekiye verildi.

## TANIK VE DELİL NOTU
Müşteki olay yerini gösterir kamera kayıtlarının da incelenmesini talep etmiştir.
Konak Polis Merkezi Amirliği Sabit Telefon: 0232 441 11 00
Dosya Kayıt Sıra No: KNK-2025-1402

Müşteki
Cemre Doğan

İfadeyi Alan Görevli
Polis Memuru İbrahim Çelik (Sicil No: 348912)
Saat: 22:45
"""

    kolluk_supheli = f"""# İZMİR İL EMNİYET MÜDÜRLÜĞÜ KONAK POLİS MERKEZİ AMİRLİĞİ
## ŞÜPHELİ İFADE TUTANAĞI

**SORUŞTURMA NO:** 2025/1402
**TARİH:** 06.01.2025 - SAAT: 11:00

**İFADEYİ ALAN GÖREVLİ:** Polis Memuru İbrahim Çelik (Sicil No: 348912)

**ŞÜPHELİ:** Volkan Tekin (T.C. Kimlik No: {tc_supheli})
**BABA ADI:** Ahmet  **ANA ADI:** Nermin  **DOĞUM TARİHİ:** 09.04.1989
**İKAMET ADRESİ:** Liman Caddesi No: 5/1 Konak/İzmir
**CEP TELEFONU:** 0531 445 66 77
**MÜDAFİ:** Av. Caner Akın (İzmir Barosu Sicil No: 45123)

## YASAL HAKLAR
Şüpheliye CMK m. 147 uyarınca isnat edilen kasten yaralama suçu anlatıldı;
susma hakkı, müdafiden yararlanma hakkı ve lehine olan delillerin toplanmasını
isteme hakkı hatırlatıldı.

## İFADE
Müdafii Av. Caner Akın huzurunda beyanı alındı:
"Ben Barış Parkı girişi yakınında müşteki Cemre Doğan ile karşılaştım. Aramızda
önceki park meselesinden dolayı sözlü tartışma çıktı, kendisi üzerime yürüyünce
kendimi korumak için itmek zorunda kaldım. Kesinlikle kasten yaralama kastım
yoktu ve yumruk atmadım. Olay sırasında yakınımızda bulunan tanık Yusuf Karahan
(TCKN: {tc_tanik}) kimin önce saldırdığını görmüştür. Üzerime atılı suçlamayı
kabul etmiyorum."

Okunan tutanak imzalandı.
Şüpheli kimlik ve adres bilgilerinin doğruluğunu beyan etti.
Müdafi Av. Caner Akın müvekkili hakkında adli kontrol veya tutuklama talebi
bulunmamasını ve serbest bırakılmasını talep etti.
İfade alma işlemi saat 11:40 itibarıyla sonlandırıldı.
Şüphelinin parmak izi ve fotoğraf kayıtları usulünce alındı.
Cumhuriyet Savcısının talimatı doğrultusunda şüpheli ifadesi sonrası serbest bırakıldı.
Evrak dizi pusulasına bağlandı.

Şüpheli: Volkan Tekin
Müdafi: Av. Caner Akın
Polis Memuru İbrahim Çelik (Sicil No: 348912)
"""

    adli_rapor = f"""# İZMİR BOZYAKA EĞİTİM VE ARAŞTIRMA HASTANESİ
## ADLİ MUAYENE RAPORU

**PROTOKOL NO:** 2025-8812
**TARİH:** 05.01.2025
**SAAT:** 21:10
**İSTEK YAPAN MAKAM:** İzmir Konak Polis Merkezi Amirliği

**MUAYENE EDİLEN (MÜŞTEKİ):** Cemre Doğan (TCKN: {tc_musteki})
**ADRES:** Çınarlı Sokak No: 22/6 Konak/İzmir
**MUAYENEYİ YAPAN HEKİM:** Dr. Ece Vural (Acil Tıp Uzmanı)

## ANAMNEZ VE FİZİK MUAYENE
05.01.2025 tarihinde saat 21:10'da polis eşliğinde acil servise getirilen
Cemre Doğan, saat 20:30 sıralarında darp edildiğini ifade etmiştir.
Yapılan fiziki muayenesinde:
1. Sol zigomatik bölgede 2x2 cm boyutlarında taze ekimoz ve hafif ödem,
2. Sol ön kol dış yüzde 3 cm uzunluğunda yüzeyel sıyrık tespit edilmiştir.
3. Kranial tomografi ve ön kol grafisinde kemik kırığı veya intrakranial
   patoloji saptanmamıştır.
4. Hastanın bilinci açık, koopere ve oryantedir; hayati tehlike bulgusu yoktur.

## KANAAT VE SONUÇ
Şahıstaki yaralanmanın;
- Yaşamını tehlikeye sokan bir durum OLMADIĞI,
- Basit bir tıbbi müdahale ile giderilebilecek ölçüde hafif nitelikte olduğu
kanaatine varılmıştır.

İşbu kati adli rapor adli makamlara sunulmak üzere düzenlenmiştir.
Raporun bir nüshası hastane arşivinde muhafaza edilmektedir.
Diğer nüsha kapalı zarf içinde Konak Polis Merkezi Amirliği görevlisine teslim edildi.
Muayene sırasında hastanın rızası alınmıştır.
Acil servis müdahale ücreti SGK kapsamında kayıt altına alınmıştır.
Düzenleme Saati: 21:55
Onay Kodu: HAST-2025-8812

Dr. Ece Vural
Acil Tıp Uzmanı
İzmir Bozyaka Eğitim ve Araştırma Hastanesi
Hastane Sabit Hat: 0232 250 50 50
Belge No: ADLI-2025-8812
"""

    iddianame = f"""# T.C. İZMİR CUMHURİYET BAŞSAVCILIĞI
## İDDİANAME

**SORUŞTURMA NO:** 2025/1402
**İDDİANAME NO:** 2025/510
**MAHKEMESİ:** İzmir 14. Asliye Ceza Mahkemesi
**CUMHURİYET SAVCISI:** Cumhuriyet Savcısı Mehmet Ali Polat (Sicil: 194520)

**MÜŞTEKİ:** Cemre Doğan (TCKN: {tc_musteki})
**ADRES:** Çınarlı Sokak No: 22/6 Konak/İzmir
**CEP TEL:** 0530 112 33 44

**ŞÜPHELİ:** Volkan Tekin (TCKN: {tc_supheli})
**ADRES:** Liman Caddesi No: 5/1 Konak/İzmir
**CEP TEL:** 0531 445 66 77
**MÜDAFİ:** Av. Caner Akın

**SUÇ:** Kasten Yaralama (TCK m. 86/2)
**SUÇ TARİHİ VE YERİ:** 05.01.2025 - Barış Parkı girişi, Konak/İzmir
**SEVK MADDELERİ:** TCK m. 86/2, 53/1

## DELİLLER VE HUKUKİ DEĞERLENDİRME
Dosya kapsamında alınan müşteki Cemre Doğan beyanı, tanık Yusuf Karahan'ın
beyanı, Dr. Ece Vural imzalı adli muayene raporu ve şüpheli Volkan Tekin
savunması birlikte değerlendirildiğinde; şüphelinin Barış Parkı girişi önünde
müştekiye yumrukla vurarak basit tıbbi müdahale ile giderilebilir şekilde
yaraladığı sabit olmuştur.

Suçun uzlaştırma kapsamında kalması nedeniyle dosya uzlaştırma bürosuna tevdi
edilmiş ancak tarafların uzlaşamadığı tutanakla belirlenmiştir.

## SONUÇ VE TALEP
Şüpheli Volkan Tekin'in eylemine uyan TCK m. 86/2 ve 53. maddeleri uyarınca
İzmir 14. Asliye Ceza Mahkemesi nezdinde yargılanarak cezalandırılması kamu
adına talep ve iddia olunur.

## EKLER
1. Müşteki ve şüpheli ifade tutanakları,
2. Adli muayene raporu ve uzlaştırma başarısızlık tutanağı,
3. Nüfus ve adli sicil kayıtları,
4. Olay yeri kamera tutanağı.

İddianame UYAP üzerinden elektronik imza ile düzenlenerek İzmir 14. Asliye Ceza
Mahkemesine sunulmuştur.

Cumhuriyet Savcısı Mehmet Ali Polat (194520)
"""

    durusma_karar = f"""# T.C. İZMİR 14. ASLİYE CEZA MAHKEMESİ
## DURUŞMA ZAPTI VE GEREKÇELİ KARAR

**ESAS NO:** 2025/203 E.
**KARAR NO:** 2025/311 K.
**HAKİM:** Hâkim Ayşe Nur Sönmez (Sicil: 182310)
**KATİP:** Zabıt Kâtibi Berkay Koç
**TARİH:** 12.06.2025

**KATILAN:** Cemre Doğan (TCKN: {tc_musteki}, Tel: 0530 112 33 44)
**SANIK:** Volkan Tekin (TCKN: {tc_supheli}, Tel: 0531 445 66 77)
**SANIK MÜDAFİİ:** Av. Caner Akın
**TANIK:** Yusuf Karahan (TCKN: {tc_tanik})

## DURUŞMA ÖZETİ
Belirli gün ve saatte celse açıldı. Katılan Cemre Doğan ile sanık Volkan Tekin
ve müdafii Av. Caner Akın duruşmada hazır bulundu. Tanık Yusuf Karahan yeminli
olarak dinlenildi; olay anında sanığın müştekiye yumruk attığını beyan etti.
Cumhuriyet Savcısı esas hakkındaki mütalaasında cezalandırma talep etti.

## HÜKÜM ÖZETİ
1. Sanık Volkan Tekin'in katılan Cemre Doğan'a yönelik kasten yaralama suçunu
   işlediği tanık Yusuf Karahan beyanı ve adli rapor ile sabit olduğundan TCK m. 86/2
   uyarınca 4 ay hapis cezası ile cezalandırılmasına,
2. Sanık Volkan Tekin hakkında verilen cezanın TCK m. 50 uyarınca adli para
   cezasına çevrilmesine,
3. Katılan Cemre Doğan'ın CMK m. 237 uyarınca katılma talebinin kabulüne,
4. Yargılama giderlerinin sanıktan tahsiline karar verildi.

## KESİNLEŞME VE TEBLİĞ NOTU
Karar hazır bulunan tarafların yüzlerine karşı açıkça okunup anlatıldı;
yedi günlük yasal süre içinde İzmir Bölge Adliye Mahkemesi nezdinde istinaf
kanun yoluna başvurma hakları hatırlatıldı.
Katılan vekaletnamesi bulunmadığından karar asile tefhim edildi.
Duruşmaya saat 14:25 itibarıyla son verildi.
Karar UYAP ortamında elektronik imza ile onaylanmıştır.

Hâkim Ayşe Nur Sönmez (182310)
Zabıt Kâtibi Berkay Koç
Duruşma Sonu Saati: 14:25
UYAP Evrak No: 2025-311-K
"""

    return Senaryo(
        ad="04_ceza_kasten_yaralama",
        baslik="Ceza: Kasten Yaralama (Rol Değişimi + Sicil)",
        dosyalar={
            "01_Kolluk_Ifade_Tutanagi_Musteki.md": kolluk_musteki,
            "Ifadeler/Supheli_Volkan_Tekin_Ifade_Tutanagi.md": kolluk_supheli,
            "03_Adli_Muayene_Raporu.md": adli_rapor,
            "04_Iddianame.md": iddianame,
            "05_Durusma_Zapti_ve_Karar.md": durusma_karar,
        },
        gizli=[
            tc_musteki, tc_supheli, tc_tanik,
            "348912", "45123", "194520", "182310",
            "0530 112 33 44", "0531 445 66 77", "0537 889 10 20",
            "Çınarlı Sokak No: 22/6", "Liman Caddesi No: 5/1",
            "Cemre Doğan", "Volkan Tekin", "Yusuf Karahan",
            "Volkan_Tekin", "Ayşe Nur Sönmez", "Mehmet Ali Polat", "Berkay Koç",
        ],
        korunan=[
            "Polis Memuru İbrahim Çelik",
            "Dr. Ece Vural",
            "Av. Caner Akın",
            "Barış Parkı girişi",
            "TCK m. 86/2",
            "İzmir 14. Asliye Ceza Mahkemesi",
            "2025/203 E.",
        ],
        kisiler={
            "Cemre Doğan": "MÜŞTEKİ",
            "Volkan Tekin": "ŞÜPHELİ",
            "Yusuf Karahan": "TANIK",
            "Ayşe Nur Sönmez": "HAKİM",
            "Mehmet Ali Polat": "SAVCI",
            "Berkay Koç": "KÂTİP",
        },
        ayni_etiket=[
            ["Volkan Tekin"],
            ["Cemre Doğan"],
            ["348912"],
            [tc_supheli],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 5: Ceza — Dolandırıcılık
# ---------------------------------------------------------------------------
def _build_senaryo_05() -> Senaryo:
    tc_sup1 = _make_tckn("112233445")
    tc_sup2 = _make_tckn("223344556")
    tc_mag1 = _make_tckn("334455667")
    tc_mag2 = _make_tckn("445566778")
    tc_mag3 = _make_tckn("556677889")
    tc_mag4 = _make_tckn("667788991")

    iban1 = _make_iban("00062", "0011223344556677")
    iban2 = _make_iban("00046", "0022334455667788")
    iban3 = _make_iban("00010", "0033445566778899")
    iban4 = _make_iban("00064", "0044556677889900")

    kart1 = _make_card("453271002233445")
    kart1_sp = " ".join(kart1[i:i + 4] for i in range(0, 16, 4))
    kart1_dash = "-".join(kart1[i:i + 4] for i in range(0, 16, 4))
    kart2 = _make_card("540012003344556")
    kart2_sp = " ".join(kart2[i:i + 4] for i in range(0, 16, 4))

    hesap_mag1 = "77192038"
    hesap_sup1 = "88301945"
    musteri_no = "990182734"

    fezleke = f"""# BURSA İL EMNİYET MÜDÜRLÜĞÜ SİBER SUÇLARLA MÜCADELE ŞUBE MÜDÜRLÜĞÜ
## SORUŞTURMA FEZLEKESİ

**SORUŞTURMA NO:** 2025/3900
**TARİH:** 10.02.2025

**ŞÜPHELİ 1:** Kadir Şen (TCKN: {tc_sup1}, Tel: 0532 555 11 00)
**ADRES:** Yıldırım Beyazıt Caddesi No: 11/2 Osmangazi/Bursa

**ŞÜPHELİ 2:** Oğuzhan Bal (TCKN: {tc_sup2}, Tel: 0541 666 22 00)
**ADRES:** Çekirge Sokak No: 4/9 Osmangazi/Bursa

**MAĞDURLAR:**
1. Derya Yavuz (TCKN: {tc_mag1})
2. Emrah Güneş (TCKN: {tc_mag2})
3. Tuğba Korkut (TCKN: {tc_mag3})
4. İsmail Erdem (TCKN: {tc_mag4})

## OLAY ÖZETİ
1. Şüpheliler Kadir Şen ve Oğuzhan Bal'ın sahte araç ilanı siteleri üzerinden
   mağdurlardan kapora adı altında para topladığı tespit edilmiştir.
2. Toplanan tutarların MASAK raporlarına göre {iban1} ve {iban2} IBAN numaralı
   hesaplara aktarıldığı, toplam zararın 101.250,00 TL olduğu belirlenmiştir.
3. Şüpheli Kadir Şen adına tanımlı banka kartı ({kart1_sp}) ile Bursa merkezdeki
   ATM'lerden nakit çekim yapıldığı güvenlik kamera kayıtlarıyla saptanmıştır.
4. Şüpheli Oğuzhan Bal'ın ise {kart2_sp} numaralı kart üzerinden kripto varlık
   platformuna transfer gerçekleştirdiği dijital inceleme raporuyla doğrulanmıştır.
5. HTS baz istasyonu kayıtları her iki şüphelinin suç tarihlerinde aynı bölgede
   birlikte hareket ettiklerini göstermektedir.

## DELİLLER
- MASAK mali analiz raporu,
- Türkiye Garanti Bankası A.Ş. Etiler Şubesi hesap ekstreleri,
- Mağdur beyanları ve ATM kamera görüntüleri.

## SONUÇ
Şüphelilerin TCK m. 158/1-f kapsamında nitelikli dolandırıcılık suçundan
Bursa Cumhuriyet Başsavcılığına sevki arz olunur.

Siber Suçlar Büro Amiri Komiser Murat Aydın
"""

    banka_dekont = f"""# TÜRKİYE GARANTİ BANKASI A.Ş. ETİLER ŞUBESİ
## BANKA HESAP HAREKETLERİ VE DEKONT KAYITLARI

**ŞUBE ADRESİ:** Nispetiye Caddesi No: 24 Beşiktaş/İstanbul
**İLGİLİ DOSYA:** Bursa 3. Ağır Ceza Mahkemesi 2025/188 E.
**TARİH:** 18.02.2025
**ŞUBE SABİT TELEFON:** 0212 351 90 00

## HESAP ÖZETLERİ
1. **Hesap Sahibi:** Kadir Şen (TCKN: {tc_sup1})
   - Müşteri No: {musteri_no}
   - Hesap No: {hesap_sup1}
   - IBAN: {iban1}
   - Bağlı Kart No: {kart1_dash}

2. **Hesap Sahibi:** Oğuzhan Bal (TCKN: {tc_sup2})
   - IBAN: {iban2}
   - Bağlı Kart No: {kart2_sp}

## DEKONT HAREKETLERİ
- 14.01.2025 | Referans: BPM-20250114-01 | Gönderen Derya Yavuz (Hesap No: {hesap_mag1},
  IBAN: {iban3}) -> Alıcı Kadir Şen (IBAN: {iban1}) | Tutar: 42.500,00 TL
- 15.01.2025 | Referans: BPM-20250115-02 | Gönderen Emrah Güneş (IBAN: {iban4}) ->
  Alıcı Kadir Şen (IBAN: {iban1}) | Tutar: 18.750,00 TL
- 16.01.2025 | Referans: BPM-20250116-03 | Gönderen Tuğba Korkut ->
  Alıcı Oğuzhan Bal (IBAN: {iban2}) | Tutar: 25.000,00 TL
- 17.01.2025 | Referans: BPM-20250117-04 | Gönderen İsmail Erdem ->
  Alıcı Oğuzhan Bal (IBAN: {iban2}) | Tutar: 15.000,00 TL

## ATM ÇEKİM KAYITLARI
- 14.01.2025 Saat 15:42 - Kart: {kart1_dash} - Çekilen: 20.000,00 TL
- 15.01.2025 Saat 16:10 - Kart: {kart1_dash} - Çekilen: 18.000,00 TL
- 16.01.2025 Saat 14:05 - Kart: {kart2_sp} - POS Transfer: 24.500,00 TL

## ONAY
İşbu dekont kayıtları Türkiye Garanti Bankası A.Ş. Etiler Şubesi sisteminden
Bursa 3. Ağır Ceza Mahkemesi müzekkeresi uyarınca alınmıştır.
Kayıtlar bankanın merkezi arşiv veri tabanından doğrulanmıştır.
Elektronik dekont doğrulama numarası: GRT-2025-881203
Şube Yetkilisi: Serpil Kaya
Tarih: 18.02.2025
"""

    magdur_ifadeler = f"""# MAĞDUR İFADE TUTANAKLARI TOPLU ÖZETİ

**SORUŞTURMA NO:** 2025/3900
**TARİH:** 20.01.2025

## 1. MAĞDUR: Derya Yavuz
- T.C. Kimlik No: {tc_mag1}
- Adres: Nilüfer Caddesi No: 8/3 Nilüfer/Bursa
- Tel: 0535 123 45 67
- İfade: "İnternette gördüğüm araç ilanı üzerine 0532 555 11 00 numaralı
  telefondan kendisini Kadir Şen olarak tanıtan kişiyle görüştüm. Aracı
  başka alıcıya satmaması için kapora istedi. Ben de {hesap_mag1} hesap
  numaralı kendi hesabımdan 42.500,00 TL tutarını {iban1} IBAN'a gönderdim.
  Parayı gönderdikten sonra telefonunu kapattı. Şikâyetçiyim."

## 2. MAĞDUR: Emrah Güneş
- T.C. Kimlik No: {tc_mag2}
- Adres: Cumhuriyet Sokak No: 16/4 Osmangazi/Bursa
- Tel: 0536 234 56 78
- İfade: "18.750,00 TL kapora parasını {iban4} IBAN'lı hesabımdan gönderdim.
  Karşı taraf dekont istedikten sonra beni engelledi. Zararımın giderilmesini
  ve şüphelilerin cezalandırılmasını istiyorum."

## 3. MAĞDUR: Tuğba Korkut
- T.C. Kimlik No: {tc_mag3}
- Adres: Lale Sokak No: 3/1 Yıldırım/Bursa
- Tel: 0538 345 67 89
- İfade: "Oğuzhan Bal tarafından verilen {iban2} IBAN'a 25.000,00 TL yatırdım.
  İlanda yazan ekspertiz raporu sahte çıktı, şikâyetçiyim."

## 4. MAĞDUR: İsmail Erdem
- T.C. Kimlik No: {tc_mag4}
- Adres: Fidan Sokak No: 29/7 Nilüfer/Bursa
- Tel: 0539 456 78 90
- İfade: "Şüphelilerin yönlendirmesiyle 15.000,00 TL ödeme yaptım,
  dolandırıldığımı anlayınca karakola başvurdum, şikâyetçiyim."

## ORTAK TUTANAK NOTU
1. Mağdurların tamamı uzlaşmak istemediklerini ayrı ayrı beyan etmiştir.
2. Tüm mağdurlar tarafından sunulan dekontlar dosya ekine alınmıştır.
3. İşbu özet tutanak soruşturma dosyası kapsamında hazırlanmıştır.
"""

    iddianame = f"""# T.C. BURSA CUMHURİYET BAŞSAVCILIĞI
## İDDİANAME

**ESAS NO:** 2025/188 E.
**MAHKEMESİ:** Bursa 3. Ağır Ceza Mahkemesi
**CUMHURİYET SAVCISI:** Cumhuriyet Savcısı Faruk Öztürk

**ŞÜPHELİ:** Kadir Şen (TCKN: {tc_sup1}) - Müdafi: Av. Pelin Soylu
**ŞÜPHELİ:** Oğuzhan Bal (TCKN: {tc_sup2})

**MAĞDURLAR:**
- Derya Yavuz (TCKN: {tc_mag1})
- Emrah Güneş (TCKN: {tc_mag2})
- Tuğba Korkut (TCKN: {tc_mag3})
- İsmail Erdem (TCKN: {tc_mag4})

**SUÇ:** Bilişim Sistemlerinin Araç Olarak Kullanılması Suretiyle Dolandırıcılık
(TCK m. 158/1-f, m. 43/1)

## DELİLLER VE DEĞERLENDİRME
1. MASAK verileri ve Türkiye Garanti Bankası A.Ş. Etiler Şubesi dekontları
   doğrultusunda; şüpheliler Kadir Şen ile Oğuzhan Bal'ın fikir ve eylem
   birliği içinde hareket ettikleri belirlenmiştir.
2. Şüphelilerin sahte ilanlar üzerinden mağdurlar Derya Yavuz, Emrah Güneş,
   Tuğba Korkut ve İsmail Erdem'i aldatıp {iban1} ve {iban2} numaralı hesaplar
   aracılığıyla haksız menfaat temin ettikleri anlaşılmıştır.
3. Şüpheli Kadir Şen savunmasında hesabını arkadaşına verdiğini ileri sürmüş ise
   de ATM kamera görüntüleri ve {kart1_sp} numaralı kart kullanım kayıtları
   savunmasını çürütmektedir.

## SONUÇ VE TALEP
Şüphelilerin üzerlerine atılı TCK m. 158/1-f suçundan Bursa 3. Ağır Ceza
Mahkemesi nezdinde yargılanarak ayrı ayrı cezalandırılmaları, ayrıca elde
edilen haksız kazancın TCK m. 55 gereğince müsaderesi kamu adına talep
olunur.

## EKLER
- MASAK raporu,
- Banka hesap hareketleri,
- Mağdur ifade tutanakları.

Cumhuriyet Savcısı Faruk Öztürk
"""

    return Senaryo(
        ad="05_ceza_dolandiricilik",
        baslik="Ceza: Dolandırıcılık (IBAN, Hesap, Kart, 4 Mağdur)",
        dosyalar={
            "01_Sorusturma_Fezlekesi.md": fezleke,
            "02_Banka_Hesap_Hareketleri_ve_Dekontlar.md": banka_dekont,
            "03_Magdur_Ifade_Tutanaklari.md": magdur_ifadeler,
            "04_Iddianame.md": iddianame,
        },
        gizli=[
            tc_sup1, tc_sup2, tc_mag1, tc_mag2, tc_mag3, tc_mag4,
            iban1, iban2, iban3, iban4,
            hesap_mag1, hesap_sup1, musteri_no,
            kart1_sp, kart1_dash, kart2_sp,
            "0532 555 11 00", "0541 666 22 00", "0535 123 45 67",
            "0536 234 56 78", "0538 345 67 89", "0539 456 78 90",
            "Yıldırım Beyazıt Caddesi No: 11/2", "Çekirge Sokak No: 4/9",
            "Nilüfer Caddesi No: 8/3", "Cumhuriyet Sokak No: 16/4",
            "Lale Sokak No: 3/1", "Fidan Sokak No: 29/7",
            "Kadir Şen", "Oğuzhan Bal", "Derya Yavuz", "Emrah Güneş", "Tuğba Korkut", "İsmail Erdem",
            "Faruk Öztürk",
        ],
        korunan=[
            "Türkiye Garanti Bankası A.Ş. Etiler Şubesi",
            "Nispetiye Caddesi No: 24 Beşiktaş/İstanbul",
            "MASAK",
            "Bursa 3. Ağır Ceza Mahkemesi",
            "TCK m. 158/1-f",
            "Av. Pelin Soylu",
            "42.500,00 TL",
            "18.750,00 TL",
            "0212 351 90 00",
        ],
        kisiler={
            "Kadir Şen": "ŞÜPHELİ",
            "Oğuzhan Bal": "ŞÜPHELİ",
            "Derya Yavuz": "MAĞDUR",
            "Emrah Güneş": "MAĞDUR",
            "Tuğba Korkut": "MAĞDUR",
            "İsmail Erdem": "MAĞDUR",
            "Faruk Öztürk": "SAVCI",
        },
        ayni_etiket=[
            [iban1],
            [kart1_sp, kart1_dash],
            [hesap_mag1],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 6: Trafik Kazası Tazminatı
# ---------------------------------------------------------------------------
def _build_senaryo_06() -> Senaryo:
    tc_davaci = _make_tckn("198273645")
    tc_davali = _make_tckn("287364519")
    seri_davaci = "A14K82931"
    iban_davaci = _make_iban("00032", "0056789012345678")

    kaza_tutanagi = f"""# TRAFİK KAZASI TESPİT TUTANAĞI

**TUTANAK NO:** 2024-IST-88412
**KAZA TARİHİ / SAATİ:** 14.09.2024 - 16:40
**KAZA YERİ:** Bağdat Caddesi ile Şemsettin Günaltay Caddesi Kavşağı, Kadıköy/İstanbul
**HAVA VE YOL DURUMU:** Açık, kuru asfalt, görüş mesafesi net, sinyalizasyon faal.

## ARAÇ A (MAĞDUR / DAVACI)
- **Sürücü:** Sinan Toprak (T.C. Kimlik No: {tc_davaci})
- **Kimlik Seri No:** {seri_davaci}
- **Sürücü Belgesi No:** 49201188
- **Plaka:** 34 KLM 482
- **Araç Markası / Modeli:** 2022 Model Otomobil
- **İkamet Adresi:** Akasya Sokak No: 10/4 Kadıköy/İstanbul
- **GSM:** 0532 777 88 99

## ARAÇ B (KUSURLU / DAVALI SÜRÜCÜ)
- **Sürücü:** Tolga Acar (T.C. Kimlik No: {tc_davali})
- **Plaka:** 06 TZR 917
- **Sigorta Şirketi:** Anadolu Anonim Türk Sigorta Şirketi
- **Poliçe No:** POL-2024-998172
- **İkamet Adresi:** Çamlık Caddesi No: 71/2 Üsküdar/İstanbul
- **GSM:** 0543 666 55 44

## KAZA OLUŞ ŞEKLİ VE KROKİ AÇIKLAMASI
1. 34 KLM 482 plakalı araç Bağdat Caddesi üzerinde kendisine yeşil ışık
   yanması üzerine kavşağa kontrollü şekilde giriş yapmıştır.
2. Bu sırada 06 TZR 917 plakalı araç Şemsettin Günaltay Caddesi yönünden
   kırmızı ışık ihlali yaparak kavşakta 34 KLM 482 plakalı araca sol yandan
   çarpmıştır.
3. Yapılan alkol muayenesinde her iki sürücünün de 0.00 promil olduğu
   tespit edilmiştir.
4. Sürücü Tolga Acar KTK m. 47/1-b uyarınca asli kusurlu, Sinan Toprak
   kusursuz bulunmuştur.

## HASAR GÖRÜNÜMÜ VE ÇEKİCİ KAYDI
- 34 KLM 482 plakalı aracın sol ön kapı ve çamurluk kısmında göçük oluşmuştur.
- 06 TZR 917 plakalı aracın ön tampon ve far grubunda hasar meydana gelmiştir.
- Her iki araç olay yerinden çekici marifetiyle otoparka alınmıştır.
- Kaza krokisi tutanak ekinde yer almaktadır.

Düzenleyen Görevli: Trafik Polisi Murat Yılmaz
Saat: 17:30
"""

    dava_dilekcesi = f"""# İSTANBUL ANADOLU 8. ASLİYE TİCARET MAHKEMESİNE

**ESAS NO:** 2025/214 E.
**TARİH:** 06.02.2025

**DAVACI:** Sinan Toprak (TCKN: {tc_davaci}, Kimlik Seri No: {seri_davaci})
**ADRES:** Akasya Sokak No: 10/4 Kadıköy/İstanbul
**GSM:** 0532 777 88 99
**VEKİLİ:** Av. Mertcan Kaya

**DAVALI 1:** Tolga Acar (TCKN: {tc_davali})
**ADRES:** Çamlık Caddesi No: 71/2 Üsküdar/İstanbul

**DAVALI 2:** Anadolu Anonim Türk Sigorta Şirketi
**ADRES:** Büyükdere Caddesi İş Kuleleri Kule 2 Beşiktaş/İstanbul

**KONU:** Trafik kazası kaynaklı değer kaybı, araç hasarı ve maluliyet tazminatı talebidir.

## AÇIKLAMALAR
1. 14.09.2024 tarihinde Bağdat Caddesi ile Şemsettin Günaltay Caddesi Kavşağı
   mevkiinde meydana gelen kazada davalı Tolga Acar yönetimindeki 06 TZR 917 plakalı
   araç, davacı Sinan Toprak idaresindeki 34 KLM 482 plakalı araca çarpmıştır.

2. Davalı araç Anadolu Anonim Türk Sigorta Şirketi nezdinde POL-2024-998172
   numaralı ZMMS poliçesi ile sigortalıdır. Sigorta şirketine yapılan yazılı
   başvurudan sonuç alınamamıştır.

3. Kaza nedeniyle müvekkilin aracında yüksek tutarlı değer kaybı ve hasar oluşmuş,
   müvekkil ayrıca ortopedik tedavi görmüştür.

4. Tazminat ödemesinin yapılacağı davacı IBAN bilgisi: {iban_davaci}.
   Toplam 185.000,00 TL maddi ve manevi tazminat talep edilmektedir.

## DELİLLER
- Trafik Kazası Tespit Tutanağı ve MOBESE kayıtları,
- POL-2024-998172 sayılı sigorta poliçesi,
- Hastane tedavi evrakları ve eksper raporu.

Davacı Vekili
Av. Mertcan Kaya
"""

    sigorta_cevabi = f"""# ANADOLU ANONİM TÜRK SİGORTA ŞİRKETİ GENEL MÜDÜRLÜĞÜ
## DAVAYA CEVAP VE POLİÇE BİLGİ YAZISI

**GENEL MÜDÜRLÜK ADRESİ:** Büyükdere Caddesi İş Kuleleri Kule 2 Beşiktaş/İstanbul
**SABİT TELEFON:** 0212 350 40 50
**POLİÇE NO:** POL-2024-998172
**DOSYA NO:** 2025/214 E.
**TARİH:** 28.02.2025

**DAVACI:** Sinan Toprak (TCKN: {tc_davaci})
**SİGORTALI / SÜRÜCÜ:** Tolga Acar (TCKN: {tc_davali}) - Plaka: 06 TZR 917
**MAĞDUR ARAÇ PLAKA:** 34 KLM 482

## AÇIKLAMALAR
1. Müvekkil Anadolu Anonim Türk Sigorta Şirketi, 06 TZR 917 plakalı aracın
   POL-2024-998172 sayılı poliçe ile zorunlu mali sorumluluk sigortacısıdır.
2. Davalı şirket poliçe limiti dahilinde ve yalnızca kusur oranı nispetinde
   gerçek zarardan sorumlu olup manevi tazminat talebinden sorumlu değildir.
3. Davacının talep ettiği 185.000,00 TL tutar fahiş olup aktüer ve makine
   mühendisi bilirkişi incelemesi ile gerçek değer kaybı hesaplanmalıdır.
4. Davacı Sinan Toprak'ın IBAN numarası ({iban_davaci}) hasar dosyasında kayıtlıdır.
5. Kusur ve hasar tespiti için ATK Trafik İhtisas Dairesi raporu beklenmelidir.

## SONUÇ
Manevi tazminat yönünden davanın usulden reddine, maddi tazminat yönünden ise
poliçe limitleri çerçevesinde inceleme yapılmasına karar verilmesini arz ederiz.

## EK BELGELER
1. POL-2024-998172 numaralı sigorta poliçesi örneği,
2. Eksper ön inceleme raporu,
3. Hasar ihbar dosyası kapak yazısı,
4. Vekâletname ve baro pulu sureti.

## İLETİŞİM BİLGİLERİ
- Genel Müdürlük: Büyükdere Caddesi İş Kuleleri Kule 2 Beşiktaş/İstanbul
- Sabit Hat: 0212 350 40 50
- Kurumsal E-posta: hukuk@anadolusigorta.example.tr

Anadolu Anonim Türk Sigorta Şirketi Vekili
Av. Hande Öztürk
"""

    atk_raporu = f"""# ADLİ TIP KURUMU TRAFİK İHTİSAS DAİRESİ RAPORU

**MAHKEME:** İstanbul Anadolu 8. Asliye Ticaret Mahkemesi
**ESAS NO:** 2025/214 E.
**RAPOR NO:** 2025/ATK-4410
**TARİH:** 02.04.2025

**DAVACI SÜRÜCÜ:** Sinan Toprak (34 KLM 482)
**DAVALI SÜRÜCÜ:** Tolga Acar (06 TZR 917)

## HEYET
- Prof. Dr. Haluk Ergin (Adli Tıp Uzmanı)
- Makine Mühendisi Bilirkişi Orhan Taş

## DOSYA EVRAKI VE TEKNİK İNCELEME
Mahkemenizce gönderilen dosya içindeki kaza tespit tutanağı, kavşak sinyalizasyon
faz planı, araç fotoğrafları ve tanık beyanları heyetimizce incelenmiştir.

## KUSUR DEĞERLENDİRMESİ
14.09.2024 günü saat 16:40'ta Bağdat Caddesi ile Şemsettin Günaltay Caddesi
Kavşağı üzerinde meydana gelen trafik kazasında;
- 06 TZR 917 plakalı araç sürücüsü Tolga Acar kırmızı ışık ihlali yaparak
  KTK m. 47/1-b kuralını ihlal ettiğinden %100 oranında ASLİ KUSURLUDUR.
- 34 KLM 482 plakalı araç sürücüsü Sinan Toprak yeşil ışıkta kavşağa girmiş
  olup kendisine atfedilecek KUSUR YOKTUR.

## SONUÇ
İşbu rapor dosya kapsamına uygun olarak oybirliği ile tanzim edilmiştir.

## TEKNİK DAYANAKLAR
- 2918 sayılı Karayolları Trafik Kanunu m. 47, m. 52, m. 84,
- Karayolları Trafik Yönetmeliği m. 101,
- Kavşak sinyalizasyon zaman çizelgesi (faz-1 ve faz-2 süreleri),
- Olay yeri trafik polis kroki ölçümleri.

Rapor İstanbul Anadolu 8. Asliye Ticaret Mahkemesine sunulmak üzere
dört sayfa olarak düzenlenmiştir.

Prof. Dr. Haluk Ergin
Makine Mühendisi Bilirkişi Orhan Taş
"""

    return Senaryo(
        ad="06_trafik_kazasi_tazminat",
        baslik="Trafik Kazası Tazminatı (Plaka, Poliçe, ATK)",
        dosyalar={
            "01_Kaza_Tespit_Tutanagi.md": kaza_tutanagi,
            "02_Dava_Dilekcesi.md": dava_dilekcesi,
            "03_Sigorta_Police_ve_Hasar_Cevabi.md": sigorta_cevabi,
            "04_ATK_Trafik_Ihtisas_Raporu.md": atk_raporu,
        },
        gizli=[
            tc_davaci, tc_davali, seri_davaci, iban_davaci,
            "0532 777 88 99", "0543 666 55 44",
            "Akasya Sokak No: 10/4", "Çamlık Caddesi No: 71/2",
            "Sinan Toprak", "Tolga Acar",
        ],
        korunan=[
            "34 KLM 482", "06 TZR 917",
            "Anadolu Anonim Türk Sigorta Şirketi",
            "POL-2024-998172",
            "Bağdat Caddesi ile Şemsettin Günaltay Caddesi Kavşağı",
            "Büyükdere Caddesi İş Kuleleri Kule 2 Beşiktaş/İstanbul",
            "0212 350 40 50",
            "Prof. Dr. Haluk Ergin",
            "Makine Mühendisi Bilirkişi Orhan Taş",
            "Av. Mertcan Kaya",
            "Av. Hande Öztürk",
            "185.000,00 TL",
        ],
        kisiler={
            "Sinan Toprak": "DAVACI",
            "Tolga Acar": "DAVALI",
        },
        ayni_etiket=[
            ["Sinan Toprak"],
            [seri_davaci],
            [iban_davaci],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 7: Kira Tahliye / Kira Tespiti
# ---------------------------------------------------------------------------
def _build_senaryo_07() -> Senaryo:
    tc_davaci = _make_tckn("135792468")
    tc_davali = _make_tckn("246813579")
    iban_davaci = _make_iban("00067", "0076543210987654")

    kira_sozlesmesi = f"""# KONUT KİRA SÖZLEŞMESİ ÖZETİ

**SÖZLEŞME NO:** KS-2020-0501
**BAŞLANGIÇ TARİHİ:** 01.05.2020
**SÜRE:** 1 Yıl (TBK m. 347 uyarınca uzamıştır)

**KİRAYA VEREN (DAVACI):** Nihal Sezer (T.C. Kimlik No: {tc_davaci})
**İKAMET ADRESİ:** Bağlar Sokak No: 7/3 Beşiktaş/İstanbul
**CEP TELEFONU:** 0532 101 20 30
**KİRA ÖDEME IBAN:** {iban_davaci}

**KİRACI (DAVALI):** Serkan Uçar (T.C. Kimlik No: {tc_davali})
**İKAMET ADRESİ:** Sedef Sokak No: 19/8 Kadıköy/İstanbul
**CEP TELEFONU:** 0545 303 40 50

## KİRALANAN TAŞINMAZ BİLGİLERİ
- **Taşınmazın Tapu Kaydı:** 1428 Ada 15 Parsel, 8 No'lu Bağımsız Bölüm
- **Kiralanan Adres:** Sedef Sokak No: 19/8 Kadıköy/İstanbul
- **Kullanım Amacı:** Yalnızca Mesken (Konut)
- **Mevcut Aylık Kira Bedeli:** 11.500,00 TL
- **Talep Edilen Yeni Kira Bedeli:** 28.000,00 TL

## ÖZEL ŞARTLAR
1. Kiracı taşınmazı özenle kullanmayı ve üçüncü kişilere alt kira yoluyla
   devretmemeyi kabul eder.
2. Taraflar işbu kira sözleşmesinin özel şartlarında her yıl TBK m. 344 uyarınca
   TÜFE oranında artış yapılacağını, ödemelerin {iban_davaci} hesabına
   yatırılacağını kararlaştırmışlardır.
3. Aidat ve abonelik giderleri kiracıya aittir.
4. Kiralanan taşınmazda demirbaş olarak kombi, ankastre fırın ve mutfak
   dolapları eksiksiz ve çalışır vaziyette teslim edilmiştir.
5. Kira süresi sonunda tahliye gerçekleşmezse yenilenen dönemde de aynı
   şartlar geçerli olacaktır.
6. Taraflar uyuşmazlık halinde İstanbul Anadolu Mahkemelerinin yetkili
   olduğunu kabul etmişlerdir.

## İMZA
Kiraya Veren: Nihal Sezer
Kiracı: Serkan Uçar
Tarih: 01.05.2020
Yer: Kadıköy/İstanbul
"""

    ihtarname = f"""# T.C. KADIKÖY 12. NOTERLİĞİ
## TAHLİYE VE KİRA TESPİTİ İHTARNAMESİ

**YEVMİYE NO:** 18492
**TARİH:** 10.03.2025
**NOTER:** Noter Şule Özer
**NOTERLİK ADRESİ:** Söğütlüçeşme Caddesi No: 88 Kadıköy/İstanbul

**KEŞİDECİ (DAVACI):** Nihal Sezer (TCKN: {tc_davaci})
**ADRES:** Bağlar Sokak No: 7/3 Beşiktaş/İstanbul
**VEKİLİ:** Av. Aslıhan Demir

**MUHATAP (DAVALI):** Serkan Uçar (TCKN: {tc_davali})
**ADRES:** Sedef Sokak No: 19/8 Kadıköy/İstanbul

## İHTAR KONUSU
Sayın Muhatap Serkan Uçar;
1. Maliki bulunduğum 1428 Ada 15 Parsel, 8 No'lu Bağımsız Bölüm nitelikli
   taşınmazı 01.05.2020 tarihli sözleşme ile kiracı olarak kullanmaktasınız.
2. Beş yıllık kira süresi dolmuş olup ödenmekte olan kira bedeli bölge
   rayiçlerinin oldukça altında kalmıştır.
3. TBK m. 344 uyarınca aylık kira bedelinin 01.05.2025 döneminden itibaren
   28.000,00 TL olarak {iban_davaci} hesabına ödenmesini talep ederim.
4. Ayrıca malik sıfatıyla konut ihtiyacım doğduğundan kira dönemi sonunda
   taşınmazı tahliye etmenizi, aksi halde İstanbul Anadolu 6. Sulh Hukuk
   Mahkemesi nezdinde kira tespiti ve tahliye davası açılacağını ihtaren
   bildiririz.

Sayın Noter; işbu ihtarnamenin bir suretinin muhataba tebliğini talep ederim.
Bir suretinin noterlik dairesinde saklanmasını ve tebliğ şerhli nüshasının
tarafıma verilmesini rica ederim.

Keşideci Vekili: Av. Aslıhan Demir

## NOTERLİK TASDİK ŞERHİ
İşbu ihtarname Kadıköy 12. Noterliği dairesinde tanzim ve imza edilerek
muhataba tebliğ edilmek üzere posta idaresine tevdi olunmuştur.
Noterlik Sabit Telefon: 0216 336 12 00

Kadıköy 12. Noterliği
Noter Şule Özer
"""

    dava_dilekcesi = f"""# İSTANBUL ANADOLU 6. SULH HUKUK MAHKEMESİNE

**ESAS NO:** 2025/330 E.
**TARİH:** 02.05.2025

**DAVACI:** Nihal Sezer (TCKN: {tc_davaci})
**ADRES:** Bağlar Sokak No: 7/3 Beşiktaş/İstanbul
**CEP TEL:** 0532 101 20 30
**VEKİLİ:** Av. Aslıhan Demir

**DAVALI:** Serkan Uçar (TCKN: {tc_davali})
**ADRES:** Sedef Sokak No: 19/8 Kadıköy/İstanbul
**CEP TEL:** 0545 303 40 50

**KONU:** TBK m. 344 ve m. 350 uyarınca kira bedelinin 28.000,00 TL olarak tespiti
ve konut ihtiyacı nedeniyle kiralananın tahliyesi talebidir.

## AÇIKLAMALAR
1. Davacı Nihal Sezer maliki olduğu 1428 Ada 15 Parsel, 8 No'lu Bağımsız Bölüm
   adresindeki daireyi davalı Serkan Uçar'a kiralamıştır.
2. Kiralanan taşınmaz (Sedef Sokak No: 19/8 Kadıköy/İstanbul) için beş yıllık süre
   dolmuş olup rayiç bedellerin çok altında kira ödenmektedir.
3. Kadıköy 12. Noterliği kanalıyla gönderilen ihtarnameye rağmen davalı
   taşınmazı tahliye etmemiş ve kira bedelini artırmamıştır.
4. Ödemelerin yatırıldığı {iban_davaci} hesabına ilişkin dekontlar ektedir.

## DELİLLER
- 01.05.2020 tarihli kira sözleşmesi,
- Kadıköy 12. Noterliği ihtarnamesi ve tebliğ şerhi,
- Emsal kira sözleşmeleri ve keşif,
- Tapu kaydı ve arabuluculuk son tutanağı.

## SONUÇ VE İSTEM
Yukarıda açıklanan nedenlerle aylık kira bedelinin 28.000,00 TL olarak
tespitine ve konut ihtiyacı nedeniyle tahliyeye karar verilmesini arz ederim.

Davacı Vekili
Av. Aslıhan Demir
Tarih: 02.05.2025
Ekler: Kira sözleşmesi, ihtarname sureti, vekâletname.
"""

    kesif_raporu = f"""# KEŞİF VE BİLİRKİŞİ RAPORU

**MAHKEME:** İstanbul Anadolu 6. Sulh Hukuk Mahkemesi
**ESAS NO:** 2025/330 E.
**BİLİRKİŞİ:** İnşaat Mühendisi Bilirkişi Kemal Tuna
**TARİH:** 20.06.2025

**DAVACI:** Nihal Sezer
**VEKİLİ:** Av. Aslıhan Demir
**DAVALI:** Serkan Uçar

## TAŞINMAZ TESPİTİ
1. Dava konusu 1428 Ada 15 Parsel, 8 No'lu Bağımsız Bölüm mahallinde
   (Sedef Sokak No: 19/8 Kadıköy/İstanbul) mahkeme heyeti huzurunda keşif
   yapılmıştır.
2. Keşif neticesinde konutun 115 m2, 3+1 planlı, doğalgaz kombili, asansörlü
   binada ve bakımlı durumda olduğu tespit edilmiştir.
3. Taşınmazın toplu taşıma duraklarına ve merkezi caddelere yürüme mesafesinde
   bulunduğu görülmüştür.

## EMSAL KİRA DEĞERLENDİRMESİ
Bölgedeki benzer nitelikli üç adet emsal kiralık konut ilanı ve tapu verileri
incelenmiştir.
- Emsal 1: 110 m2 daire - 27.500,00 TL
- Emsal 2: 120 m2 daire - 30.000,00 TL
- Emsal 3: 115 m2 daire - 29.000,00 TL

Taşınmazın boş olarak kiraya verilmesi halinde aylık rayiç kira bedelinin
28.000,00 TL - 30.000,00 TL aralığında olabileceği, hakkaniyet indirimi
sonrası takdirin Sayın Mahkemeye ait olduğu kanaatine varılmıştır.

## SONUÇ
İşbu rapor keşif tutanağına uygun olarak düzenlenip mahkemeye sunulmuştur.
Keşif Tarihi: 12.06.2025
Rapor Tarihi: 20.06.2025

Bilirkişi Kemal Tuna
İnşaat Mühendisi
Sicil / Oda Kayıt: İMO-2011-4410
Rapor Sayfa Sayısı: 3
"""

    return Senaryo(
        ad="07_kira_tahliye_tespit",
        baslik="Kira Tahliye / Kira Tespiti (Ada/Parsel + İkamet Adresi)",
        dosyalar={
            "01_Kira_Sozlesmesi_Ozeti.md": kira_sozlesmesi,
            "02_Tahliye_Ihtarnamesi.md": ihtarname,
            "03_Dava_Dilekcesi.md": dava_dilekcesi,
            "04_Kesif_ve_Bilirkisi_Raporu.md": kesif_raporu,
        },
        gizli=[
            tc_davaci, tc_davali, iban_davaci,
            "0532 101 20 30", "0545 303 40 50",
            "Bağlar Sokak No: 7/3", "Sedef Sokak No: 19/8",
            "Nihal Sezer", "Serkan Uçar",
        ],
        korunan=[
            "Kadıköy 12. Noterliği",
            "Noter Şule Özer",
            "Söğütlüçeşme Caddesi No: 88 Kadıköy/İstanbul",
            "1428 Ada 15 Parsel",
            "8 No'lu Bağımsız Bölüm",
            "28.000,00 TL",
            "TBK m. 344",
            "İstanbul Anadolu 6. Sulh Hukuk Mahkemesi",
            "Av. Aslıhan Demir",
        ],
        kisiler={
            "Nihal Sezer": "DAVACI",
            "Serkan Uçar": "DAVALI",
        },
        ayni_etiket=[
            ["Bağlar Sokak No: 7/3 Beşiktaş/İstanbul"],
            ["Sedef Sokak No: 19/8 Kadıköy/İstanbul"],
            [iban_davaci],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 8: Miras / Veraset (.txt dosyası dahil, aynı soyadlı 6 kişi)
# ---------------------------------------------------------------------------
def _build_senaryo_08() -> Senaryo:
    tc_muris = _make_tckn("101010101")
    tc_ahmet = _make_tckn("202020202")
    tc_mehmet = _make_tckn("303030303")
    tc_ayse = _make_tckn("404040404")
    tc_fatma = _make_tckn("505050505")
    tc_hasan = _make_tckn("606060606")

    veraset_dilekcesi = f"""# ANKARA 5. SULH HUKUK MAHKEMESİNE

**ESAS NO:** 2025/904 E.
**TARİH:** 14.03.2025

**DAVACI:** Ahmet Karabulut (TCKN: {tc_ahmet})
**ADRES:** Turgut Reis Caddesi No: 14/2 Çankaya/Ankara
**TEL:** 0532 400 10 01
**VEKİLİ:** Av. Leyla Doğan

**DAVALILAR:**
1. Mehmet Karabulut (TCKN: {tc_mehmet}) - Adres: Dikmen Sokak No: 5/6 Çankaya/Ankara
2. Ayşe Karabulut (TCKN: {tc_ayse}) - Adres: Emek Sokak No: 9/1 Çankaya/Ankara
3. Fatma Karabulut (TCKN: {tc_fatma}) - Adres: Bahçelievler Caddesi No: 3/4 Çankaya/Ankara
4. Hasan Karabulut (TCKN: {tc_hasan}) - Adres: Aydınlıkevler Sokak No: 12/8 Altındağ/Ankara

**KONU:** Muris İsmet Karabulut (TCKN: {tc_muris}) hakkında TMK m. 495 vd.
uyarınca mirasçılık belgesi verilmesi ve miras paylaşımı talebidir.

## AÇIKLAMALAR
1. Müvekkilin babası muris İsmet Karabulut 12.01.2025 tarihinde vefat etmiştir.
   Murisin Baba adı: Hasan, Anne adı: Zeynep olup doğum yeri Sivas / Merkez'dir.
2. Davacı Ahmet Karabulut ile davalılar Mehmet Karabulut, Ayşe Karabulut,
   Fatma Karabulut ve Hasan Karabulut murisin yasal mirasçılarıdır.
3. Aile bireylerinin tamamında Baba adı: İsmet ve Anne adı: Hatice olarak
   kayıtlıdır. Müvekkil Ahmet Karabulut doğum tarihi 03.07.1965'tir.
4. Murisin geride bıraktığı başkaca altsoy, evlatlık veya vasiyetname
   bulunmamaktadır.

## HUKUKİ NEDENLER VE DELİLLER
- TMK m. 495 vd., HMK m. 382 vd.
- Vukuatlı nüfus kayıt örneği, ölüm belgesi.

## SONUÇ VE İSTEM
Ankara 5. Sulh Hukuk Mahkemesi nezdinde açılan işbu davada mirasçılık
belgesinin verilmesini, yargılama giderlerinin tereke payları oranında
taraflara yükletilmesini vekâleten arz ederim.

Davacı Vekili
Av. Leyla Doğan
Ek: Vekâletname sureti
"""

    muzekkere = f"""# T.C. ANKARA 5. SULH HUKUK MAHKEMESİ
## NÜFUS MÜDÜRLÜĞÜNE MÜZEKKERE

**ESAS NO:** 2025/904 E.
**TARİH:** 18.03.2025
**GİDEN YAZI NO:** 2025/904-MÜZ-01

**ÇANKAYA İLÇE NÜFUS MÜDÜRLÜĞÜNE**
**KURUM ADRESİ:** Kızılay Mahallesi Ziya Gökalp Caddesi No: 18 Çankaya/Ankara

Ankara 5. Sulh Hukuk Mahkemesi nezdinde görülmekte olan veraset davası nedeniyle;
aşağıda açık kimlik bilgileri yazılı muris ve mirasçıları hakkında:
- Muris: İsmet Karabulut (TCKN: {tc_muris})
- Davacı: Ahmet Karabulut (TCKN: {tc_ahmet})
- Davalı: Mehmet Karabulut (TCKN: {tc_mehmet})
- Davalı: Ayşe Karabulut (TCKN: {tc_ayse})
- Davalı: Fatma Karabulut (TCKN: {tc_fatma})
- Davalı: Hasan Karabulut (TCKN: {tc_hasan})

1. Yukarıda TCKN bilgileri verilen kişilerin tam ve vukuatlı aile nüfus
   kayıt tablolarının çıkartılmasına,
2. Muris İsmet Karabulut'un eşinin vefat tarihinin teyit edilmesine,
3. TMK m. 495 uyarınca altsoy bağlarının eksiksiz olarak UYAP üzerinden
   mahkememize gönderilmesine,
4. İşbu müzekkere cevabının en geç yedi gün içinde bildirilmesine karar
   verilmiştir.

Gereği önemle rica olunur.

## MÜZEKKERE EKİ VE İRTİBAT BİLGİLERİ
- Mahkeme Kalemi Sabit Telefon: 0312 310 50 60
- KEP Adresi: ankara5sulh@hs01.kep.tr
- Cevap Süresi: 7 Gün
- Gönderim Yöntemi: UYAP Entegrasyon Sistemi

İşbu müzekkere elektronik imza ile onaylanmıştır.

Hâkim Kemal Güner
Zabıt Kâtibi Seda Kaya
Müzekkere Gönderim Tarihi: 18.03.2025
UYAP Belge Kodu: MUZ-2025-904
"""

    nufus_txt = f"""VUKUATLI NÜFUS KAYIT ÖRNEĞİ
İl: Sivas / Merkez  Mahalle/Köy: Kale  Cilt: 12  Hane: 44
Dosya: Ankara 5. Sulh Hukuk Mahkemesi 2025/904 E.

| Sıra | Yakınlık | Adı Soyadı | Baba Adı | Ana Adı | Doğum Tarihi | TCKN |
|---:|---|---|---|---|---|---|
| 1 | Muris | İsmet Karabulut | Hasan | Zeynep | 10.02.1940 | {tc_muris} |
| 2 | Çocuk | Ahmet Karabulut | İsmet | Hatice | 03.07.1965 | {tc_ahmet} |
| 3 | Çocuk | Mehmet Karabulut | İsmet | Hatice | 15.09.1968 | {tc_mehmet} |
| 4 | Çocuk | Ayşe Karabulut | İsmet | Hatice | 22.11.1971 | {tc_ayse} |
| 5 | Çocuk | Fatma Karabulut | İsmet | Hatice | 04.04.1975 | {tc_fatma} |
| 6 | Çocuk | Hasan Karabulut | İsmet | Hatice | 19.06.1979 | {tc_hasan} |

Açıklamalar:
- Muris İsmet Karabulut 12.01.2025 tarihinde vefat etmiş olup eşi Hatice kendisinden
  önce 01.03.2019 tarihinde vefat etmiştir.
- Davacı Ahmet Karabulut (Tel: 0532 400 10 01) adres: Turgut Reis Caddesi No: 14/2 Çankaya/Ankara.
- Davalı Mehmet Karabulut adres: Dikmen Sokak No: 5/6 Çankaya/Ankara.
- Davalı Ayşe Karabulut adres: Emek Sokak No: 9/1 Çankaya/Ankara.
- Davalı Fatma Karabulut adres: Bahçelievler Caddesi No: 3/4 Çankaya/Ankara.
- Davalı Hasan Karabulut adres: Aydınlıkevler Sokak No: 12/8 Altındağ/Ankara.

Kayıt Teyit Notları:
1. Aile kütüğünde başkaca evlilik kaydına rastlanmamıştır.
2. Evlat edinme veya tanıma kaydı bulunmamaktadır.
3. Tüm mirasçıların sağ olduğu MERNİS kayıtlarından doğrulanmıştır.
4. Sivas / Merkez kütük kayıtları esas alınmıştır.
5. İşbu belge 5490 sayılı Nüfus Hizmetleri Kanunu uyarınca düzenlenmiştir.

Çankaya İlçe Nüfus Müdürlüğü
Düzenleyen Memur: Nüfus Memuru Orhan Şen
Tarih: 21.03.2025
Saat: 11:20
Belge No: NUF-2025-44109
Evrak Doğrulama Kodu: 8821-4402-9910
TMK m. 495 kapsamında düzenlenmiştir.
Sayı: 2025/904 E.
İlçe/İl: Çankaya/Ankara
Belge Sayfası: 1 / 1
Bitiş satırı.
"""

    karar = f"""# T.C. ANKARA 5. SULH HUKUK MAHKEMESİ
## MİRASÇILIK BELGESİ (VERASET İLAMI)

**MAHKEME:** Ankara 5. Sulh Hukuk Mahkemesi
**ESAS NO:** 2025/904 E.
**KARAR NO:** 2025/612 K.
**TARİH:** 04.04.2025

**DAVACI:** Ahmet Karabulut (TCKN: {tc_ahmet})
**VEKİLİ:** Av. Leyla Doğan

**MURİS:** İsmet Karabulut (TCKN: {tc_muris}) - Baba adı: Hasan, Anne adı: Zeynep

## GEREKÇE
Dosya arasına celp edilen vukuatlı nüfus kayıt örneği incelendiğinde muris
İsmet Karabulut'un 12.01.2025 tarihinde vefat ettiği, eşinin kendisinden önce
vefat etmiş bulunduğu ve geriye beş çocuğunun kaldığı anlaşılmıştır.

## HÜKÜM
12.01.2025 tarihinde vefat eden muris İsmet Karabulut'un terekesinin 5 pay
kabul edilerek geriye mirasçı olarak:
1. Davacı Ahmet Karabulut (TCKN: {tc_ahmet}) - 1/5 pay,
2. Davalı Mehmet Karabulut (TCKN: {tc_mehmet}) - 1/5 pay,
3. Davalı Ayşe Karabulut (TCKN: {tc_ayse}) - 1/5 pay,
4. Davalı Fatma Karabulut (TCKN: {tc_fatma}) - 1/5 pay,
5. Davalı Hasan Karabulut (TCKN: {tc_hasan}) - 1/5 pay
bıraktığının TMK m. 495 uyarınca tespitine karar verildi.

İşbu mirasçılık belgesi aksi sabit oluncaya kadar geçerlidir.

## HARÇ VE MASRAF DÖKÜMÜ
- Başvurma Harcı: 427,60 TL (Peşin yatırılmıştır)
- Gider Avansı Bakiyesi: 150,00 TL (Karar kesinleşince iadesine)
- Vekâlet Ücreti: AAÜT gereği davacı üzerinde bırakılmasına

Karar taraflara UYAP üzerinden tebliğ edilecektir.
İstinaf kanun yolu tebliğden itibaren iki hafta süreyle açıktır.

Hâkim Kemal Güner
Zabıt Kâtibi Seda Kaya
Müzekkere Gönderim Tarihi: 18.03.2025
UYAP Belge Kodu: MUZ-2025-904
"""

    return Senaryo(
        ad="08_miras_veraset",
        baslik="Miras / Veraset (6 Aynı Soyadlı Kişi + .txt)",
        dosyalar={
            "01_Veraset_Dilekcesi.md": veraset_dilekcesi,
            "02_Nufus_Mudurlugu_Muzekkeresi.md": muzekkere,
            "03_Nufus_Kayit_Ornegi.txt": nufus_txt,
            "04_Miras_Paylasim_Karari.md": karar,
        },
        gizli=[
            tc_muris, tc_ahmet, tc_mehmet, tc_ayse, tc_fatma, tc_hasan,
            "0532 400 10 01",
            "Turgut Reis Caddesi No: 14/2", "Dikmen Sokak No: 5/6",
            "Emek Sokak No: 9/1", "Bahçelievler Caddesi No: 3/4",
            "Aydınlıkevler Sokak No: 12/8",
            "İsmet Karabulut", "Ahmet Karabulut", "Mehmet Karabulut",
            "Ayşe Karabulut", "Fatma Karabulut", "Hasan Karabulut",
            "Kemal Güner", "Seda Kaya",
        ],
        korunan=[
            "Baba adı: İsmet", "Anne adı: Hatice", "03.07.1965", "Sivas / Merkez",
            "Ankara 5. Sulh Hukuk Mahkemesi", "Av. Leyla Doğan", "TMK m. 495",
        ],
        kisiler={
            "Ahmet Karabulut": "DAVACI",
            "Mehmet Karabulut": "DAVALI",
            "Ayşe Karabulut": "DAVALI",
            "Fatma Karabulut": "DAVALI",
            "Hasan Karabulut": "DAVALI",
            "İsmet Karabulut": "KİŞİ",
            "Kemal Güner": "HAKİM",
            "Seda Kaya": "KÂTİP",
        },
        ayni_etiket=[
            [tc_ahmet],
            [tc_muris],
            ["İsmet Karabulut"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 9: Tüketici Hakem Heyeti / Ayıplı Mal
# ---------------------------------------------------------------------------
def _build_senaryo_09() -> Senaryo:
    tc_davaci = _make_tckn("173928465")
    iban_davaci = _make_iban("00062", "0087654321098765")

    basvuru = f"""# ÜMRANİYE TÜKETİCİ HAKEM HEYETİ BAŞKANLIĞINA
## TÜKETİCİ BAŞVURU FORMU

**KURUM:** Ümraniye Tüketici Hakem Heyeti
**BAŞVURU NO:** 2025/00412
**TARİH:** 08.01.2025

**BAŞVURAN / DAVACI:** Caner Başaran (T.C. Kimlik No: {tc_davaci})
**ADRES:** Lalezar Sokak No: 6/10 Ümraniye/İstanbul
**CEP TEL:** 0535 901 23 45
**E-POSTA:** caner.basaran@example.net

**ŞİKÂYET EDİLEN / DAVALI:** TeknoEv Dayanıklı Tüketim Malları A.Ş.
**MERKEZ ADRESİ:** Alemdağ Caddesi No: 120 Ümraniye/İstanbul
**VKN:** 8340192837
**MERSİS NO:** 0834019283700014
**ÇAĞRI MERKEZİ:** 0850 222 44 00 / 444 0 123
**KEP:** teknoev@hs01.kep.tr
**E-POSTA:** destek@teknoev.com.tr

## ŞİKÂYETİN KONUSU
6502 sayılı Kanun kapsamında ayıplı mal nedeniyle 34.999,00 TL bedel iadesi talebidir.

## AÇIKLAMALAR
1. 04.11.2024 tarihinde TeknoEv Dayanıklı Tüketim Malları A.Ş. mağazasından
   Fatura No: TEK2025000019283 ile 34.999,00 TL ödeyerek buzdolabı satın aldım.
2. Ürün teslimattan bir hafta sonra soğutmamaya başlamış, 0850 222 44 00
   numaralı çağrı merkezine kayıt açtırmama rağmen arıza giderilememiştir.
3. Yetkili servis parça değiştirmesine rağmen cihaz çalışmamıştır.
4. Ayıplı mal bedelinin {iban_davaci} numaralı IBAN hesabıma iadesini talep ederim.

## EKLER
- Satış faturası sureti (TEK2025000019283),
- Yetkili servis fişi (SRV-99102),
- Çağrı merkezi kayıt numaraları,
- Garanti belgesi ve ödeme dekontu.

## BEYAN
Yukarıda belirttiğim bilgilerin doğruluğunu beyan eder, 6502 sayılı Kanun
kapsamında hakem heyeti incelemesinin yapılmasını saygıyla talep ederim.

Başvuran Davacı: Caner Başaran
Tarih: 08.01.2025
"""

    fatura_servis = f"""# FATURA VE YETKİLİ SERVİS FORMU

**SATICI FİRMA:** TeknoEv Dayanıklı Tüketim Malları A.Ş.
**MERKEZ ADRESİ:** Alemdağ Caddesi No: 120 Ümraniye/İstanbul
**VKN:** 8340192837  **MERSİS NO:** 0834019283700014
**MÜŞTERİ HİZMETLERİ:** 0850 222 44 00 | 444 0 123
**KEP:** teknoev@hs01.kep.tr
**E-POSTA:** destek@teknoev.com.tr

## FATURA BİLGİLERİ
- **Fatura No:** TEK2025000019283
- **Fatura Tarihi:** 04.11.2024
- **Alıcı (Davacı):** Caner Başaran (TCKN: {tc_davaci})
- **Teslimat Adresi:** Lalezar Sokak No: 6/10 Ümraniye/İstanbul
- **İrtibat Tel:** 05359012345
- **Ürün:** FrostFree 540L Buzdolabı
- **Garanti Süresi:** 3 Yıl
- **KDV Dahil Tutar:** 34.999,00 TL

## SERVİS KAYDI (NO: SRV-99102)
- 15.11.2024 tarihinde teknisyen incelemesi yapıldı; kompresör arızası tespit edildi.
- 28.11.2024 tarihinde parça değişimi yapılmasına rağmen sorun devam etti.
- 10.12.2024 tarihinde ikinci kez servis kaydı açıldı ancak ürün soğutmadı.
- Müşteri Caner Başaran 6502 sayılı Kanun uyarınca sözleşmeden dönme hakkını
  kullanarak bedel iadesini talep etti.
- Ödeme iadesi halinde kullanılacak IBAN: {iban_davaci}

## SERVİS ONAY BÖLÜMÜ
Servis Teknisyeni: Ahmet Kaya
Müşteri İmza: Caner Başaran
Yetkili Firma Onayı: TeknoEv Dayanıklı Tüketim Malları A.Ş.

## GARANTİ VE FATURA NOTLARI
1. İşbu servis formu iki nüsha halinde düzenlenmiş, bir sureti tüketiciye
   teslim edilmiştir.
2. Cihaz seri kontrolü yapılmış, kullanıcı müdahalesi olmadığı görülmüştür.
3. E-Arşiv Fatura Doğrulama Kodu: EAR-2024-771029
4. Ürün barkodu: 8690001122334
5. Teslimat mağazası: Ümraniye Şubesi
6. Düzenleme Tarihi: 10.12.2024
"""

    thh_karari = f"""# T.C. ÜMRANİYE TÜKETİCİ HAKEM HEYETİ KARARI

**HEYEΤ:** Ümraniye Tüketici Hakem Heyeti
**KARAR NO:** 2025/190
**TARİH:** 17.02.2025

**BAŞVURAN / DAVACI:** Caner Başaran (TCKN: {tc_davaci})
**ADRES:** Lalezar Sokak No: 6/10 Ümraniye/İstanbul
**DAVALI:** TeknoEv Dayanıklı Tüketim Malları A.Ş. (VKN: 8340192837)
**MERKEZ:** Alemdağ Caddesi No: 120 Ümraniye/İstanbul

## SAVUNMA ÖZETİ
Şikâyet edilen TeknoEv Dayanıklı Tüketim Malları A.Ş. savunmasında arızanın
kullanıcı hatasından kaynaklandığını ileri sürmüş ise de teknik bilirkişi
incelemesi bu iddiayı doğrulamamıştır.

## İNCELEME VE GEREKÇE
Tüketici Caner Başaran tarafından 08.01.2025 tarihinde yapılan başvuru ve
Fatura No: TEK2025000019283 ile servis formu incelenmiştir. Ürünün teslimden
kısa süre sonra aynı arızayı tekrarladığı sabit olduğundan 6502 sayılı Kanun
m. 11 uyarınca tüketicinin sözleşmeden dönme hakkı doğmuştur.

## KARAR
1. Davacı Caner Başaran'ın talebinin KABULÜNE,
2. Ayıplı ürünün satıcıya iadesi karşılığında 34.999,00 TL fatura bedelinin
   TeknoEv Dayanıklı Tüketim Malları A.Ş. tarafından davacının {iban_davaci}
   IBAN hesabına iadesine oybirliği ile karar verildi.
3. İşbu karar 6502 sayılı Kanun m. 70/3 gereğince tebliğ tarihinden itibaren
   on beş gün içinde Tüketici Mahkemesi nezdinde itiraza tabidir.
4. Karar giderlerinin şikâyet edilen firma üzerinde bırakılmasına karar verildi.

## HEYET İMZALARI
Ümraniye Tüketici Hakem Heyeti Başkanı
Dr. Emre Önal
Üye: Av. Selda Yılmaz
Üye: Ticaret İl Müdürlüğü Temsilcisi Fatih Demir
Raportör: Burak Çelik
Karar Tebliğ Tarihi: 19.02.2025
Karar Aslı Gibidir Onayı: Ümraniye Tüketici Hakem Heyeti Kalemi
Sabit İrtibat Hattı: 0216 443 10 20
"""

    itiraz_dilekcesi = f"""# İSTANBUL ANADOLU 3. TÜKETİCİ MAHKEMESİNE

**ESAS NO:** 2025/144 E.
**TARİH:** 03.03.2025

**DAVACI (TÜKETİCİ):** Caner Başaran (TCKN: {tc_davaci})
**ADRES:** Lalezar Sokak No: 6/10 Ümraniye/İstanbul
**TEL:** 0535 901 23 45
**VEKİLİ:** Av. Koray Bilgin

**DAVALI (SATICI):** TeknoEv Dayanıklı Tüketim Malları A.Ş.
**MERKEZ ADRESİ:** Alemdağ Caddesi No: 120 Ümraniye/İstanbul
**VKN:** 8340192837  **MERSİS NO:** 0834019283700014
**KEP:** teknoev@hs01.kep.tr
**VEKİLİ:** Av. Buse Aktaş

**KONU:** Ümraniye Tüketici Hakem Heyeti kararının uygulanması ve gecikme faizi talebidir.

## AÇIKLAMALAR
1. Davacı Caner Başaran lehine verilen Ümraniye Tüketici Hakem Heyeti kararına
   rağmen davalı TeknoEv Dayanıklı Tüketim Malları A.Ş. 34.999,00 TL iadeyi
   gerçekleştirmemiştir.
2. Davalı firmanın 0850 222 44 00 ile 444 0 123 hatları ve destek@teknoev.com.tr
   adresi üzerinden yapılan tüm başvurular sonuçsuz kalmıştır.
3. 6502 sayılı Kanun uyarınca kesinleşen hakem heyeti kararının yerine
   getirilmesi zorunludur.
4. Müvekkilin {iban_davaci} hesabına ticari faiziyle ödeme yapılmasını talep ederiz.

## HUKUKİ NEDENLER VE DELİLLER
- 6502 sayılı Kanun m. 11 ve m. 70,
- Fatura No: TEK2025000019283 ve servis kayıtları,
- Ümraniye Tüketici Hakem Heyeti 2025/190 sayılı kararı,
- Çağrı merkezi kayıtları ve ihtar yazışmaları.

## SONUÇ VE İSTEM
Açıklanan nedenlerle hakem heyeti kararının uygulanmasına, 34.999,00 TL
alacağın ticari faizi ve yargılama giderleriyle davalıdan tahsiline karar
verilmesini arz ederim.

Davacı Vekili
Av. Koray Bilgin
"""

    return Senaryo(
        ad="09_tuketici_ayipli_mal",
        baslik="Tüketici Hakem Heyeti / Ayıplı Mal",
        dosyalar={
            "01_Tuketici_Basvuru_Formu.md": basvuru,
            "02_Fatura_ve_Servis_Formu.md": fatura_servis,
            "03_THH_Karari.md": thh_karari,
            "04_THH_Kararina_Itiraz_Dilekcesi.md": itiraz_dilekcesi,
        },
        gizli=[
            tc_davaci, iban_davaci,
            "0535 901 23 45", "05359012345",
            "Lalezar Sokak No: 6/10",
            "Caner Başaran",
        ],
        korunan=[
            "TeknoEv Dayanıklı Tüketim Malları A.Ş.",
            "0850 222 44 00", "444 0 123",
            "destek@teknoev.com.tr", "teknoev@hs01.kep.tr",
            "8340192837", "0834019283700014",
            "TEK2025000019283", "34.999,00 TL", "6502 sayılı Kanun",
            "Ümraniye Tüketici Hakem Heyeti", "Av. Koray Bilgin",
            "Alemdağ Caddesi No: 120 Ümraniye/İstanbul",
        ],
        kisiler={
            "Caner Başaran": "DAVACI",
        },
        ayni_etiket=[
            [tc_davaci],
            [iban_davaci],
            ["0535 901 23 45", "05359012345"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 10: Ticari Alacak (İki Şirket Taraf, Gerçek Kişi Yok)
# ---------------------------------------------------------------------------
def _build_senaryo_10() -> Senaryo:
    iban_sirket = _make_iban("00064", "0055443322110099")

    dava_dilekcesi = f"""# İSTANBUL ANADOLU 4. ASLİYE TİCARET MAHKEMESİNE

**MAHKEME:** İstanbul Anadolu 4. Asliye Ticaret Mahkemesi
**ESAS NO:** 2025/520 E.
**TARİH:** 20.01.2025

**DAVACI:** Atlas Makina Sanayi ve Ticaret A.Ş.
**VKN:** 1090456789
**MERSİS NO:** 0109045678900011
**MERKEZ ADRESİ:** Organize Sanayi Sitesi 3. Blok No: 12 Tuzla/İstanbul
**KEP ADRESİ:** atlasmakina@hs02.kep.tr
**E-POSTA:** muhasebe@atlasmakina.com.tr
**SABİT TELEFON:** 0216 555 88 99
**VEKİLİ:** Av. Berkay Demirci

**DAVALI:** Bosphorus Metal İthalat İhracat Ltd. Şti.
**VKN:** 2080123456
**MERSİS NO:** 0208012345600019
**MERKEZ ADRESİ:** Liman Yolu Caddesi No: 45 Gebze/Kocaeli
**KEP ADRESİ:** bosphorus@hs01.kep.tr
**VEKİLİ:** Av. Melis Kılıç

**KONU:** TTK m. 21 uyarınca cari hesap ve fatura alacağından doğan 1.240.000,00 TL
ticari alacağın ticari avans faiziyle tahsili talebidir.

## AÇIKLAMALAR
1. Davacı Atlas Makina Sanayi ve Ticaret A.Ş. tarafından davalı Bosphorus Metal
   İthalat İhracat Ltd. Şti.'ye muhtelif tarihlerde kesilen 6 adet fatura bedeli
   vadesinde ödenmemiştir.
2. Davalıya atlasmakina@hs02.kep.tr adresinden 15.12.2024 tarihinde ihtarname
   gönderilmiş, ancak {iban_sirket} numaralı şirket hesabına ödeme yapılmamıştır.
3. Ticari defter ve BA-BS formları incelendiğinde borcun sabit olduğu görülecektir.
4. 1.240.000,00 TL asıl alacağın davalıdan tahsili gerekmektedir.

## DELİLLER
- E-fatura kayıtları ve irsaliyeler,
- KEP ihtarnameleri ve ticari defterler.

Davacı Vekili
Av. Berkay Demirci
"""

    cevap_dilekcesi = f"""# İSTANBUL ANADOLU 4. ASLİYE TİCARET MAHKEMESİNE

**MAHKEME:** İstanbul Anadolu 4. Asliye Ticaret Mahkemesi
**ESAS NO:** 2025/520 E.
**TARİH:** 10.02.2025

**DAVALI:** Bosphorus Metal İthalat İhracat Ltd. Şti. (VKN: 2080123456)
**MERKEZ ADRESİ:** Liman Yolu Caddesi No: 45 Gebze/Kocaeli
**KEP:** bosphorus@hs01.kep.tr
**VEKİLİ:** Av. Melis Kılıç

**DAVACI:** Atlas Makina Sanayi ve Ticaret A.Ş. (VKN: 1090456789)
**MERKEZ ADRESİ:** Organize Sanayi Sitesi 3. Blok No: 12 Tuzla/İstanbul
**VEKİLİ:** Av. Berkay Demirci

## CEVAP DİLEKÇEMİZ
1. Davacı Atlas Makina Sanayi ve Ticaret A.Ş.'nin iddia ettiği 1.240.000,00 TL
   tutarındaki fatura alacağı ticari defter kayıtlarımızla örtüşmemektedir.
2. Teslim edilen ürünlerin bir kısmı ayıplı olup TTK m. 21 ve m. 23 uyarınca
   süresinde bosphorus@hs01.kep.tr adresinden ayıp ihbarı yapılmıştır.
3. İrsaliye ve kalite kontrol tutanakları incelendiğinde sevkiyatların eksik
   yapıldığı da anlaşılacaktır.
4. Ayrıca daha önce {iban_sirket} hesabına kısmi ödeme gönderilmiştir.
5. Ticari defterlerin yerinde incelenmesi ve YMM bilirkişiye tevdii talep olunur.

## DELİLLER
- 2024 yılı yevmiye ve kebir defterleri,
- KEP yazışmaları ve kalite kontrol raporları,
- Banka ödeme dekontları.

## SONUÇ VE İSTEM
Haksız davanın reddine, yargılama giderleri ve vekâlet ücretinin davacı tarafa
yükletilmesine karar verilmesini vekâleten arz ederim.

## EKLER
1. Vekâletname örneği,
2. Ticari defter açılış/kapanış tasdik suretleri,
3. Ayıp ihbarına ilişkin KEP çıktıları.

Davalı Vekili
Av. Melis Kılıç
"""

    bilirkisi_raporu = f"""# TİCARİ DEFTER VE MALİ BİLİRKİŞİ RAPORU

**MAHKEME:** İstanbul Anadolu 4. Asliye Ticaret Mahkemesi
**ESAS NO:** 2025/520 E.
**BİLİRKİŞİ:** Bilirkişi YMM Kerem Savaş
**TARİH:** 15.04.2025

**DAVACI:** Atlas Makina Sanayi ve Ticaret A.Ş. (Mersis: 0109045678900011)
**VEKİLİ:** Av. Berkay Demirci
**DAVALI:** Bosphorus Metal İthalat İhracat Ltd. Şti. (Mersis: 0208012345600019)
**VEKİLİ:** Av. Melis Kılıç

## 1. TİCARİ DEFTER TASDİK İNCELEMESİ
Her iki şirketin 2024 yılı yevmiye, kebir ve envanter defterleri açılış ve
kapanış tasdikleri yönünden TTK m. 64 uyarınca usulüne uygun bulunmuştur.

## 2. CARİ HESAP VE FATURA KARŞILAŞTIRMASI
- Davacı Atlas Makina Sanayi ve Ticaret A.Ş. kayıtlarında davalıdan alacak bakiyesi
  1.240.000,00 TL olarak görülmektedir.
- Davalı şirket ticari defterlerinde ise aynı 6 adet fatura işlenmiş olup
  herhangi bir iade faturası düzenlenmediği tespit edilmiştir.
- Banka ekstrelerinin kontrolünde {iban_sirket} hesabına davalı tarafından
  yapılmış bir ödeme kaydına rastlanmamıştır.
- BA-BS formları ile e-Fatura mutabakatı davacı kayıtlarını doğrulamaktadır.

## 3. SONUÇ
Davacı şirketin 1.240.000,00 TL asıl alacağının ticari defterler nezdinde
sabit olduğu kanaatine varılmıştır.

## 4. HEYET VE TARAF İTİRAZ NOTU
- Rapor beş sayfa ve ekli cari hesap cetveli ile birlikte düzenlenmiştir.
- İşlemiş ticari avans faizi hesabı mahkemece talep edilmesi halinde ek raporla
  hesaplanabilecektir.
- Tüm defter kayıtları Vergi Usul Kanunu ve TTK m. 64 yönünden eksiksizdir.
- Nihai hukuki takdir Sayın Mahkemeye aittir.

Bilirkişi YMM Kerem Savaş
İstanbul YMM Odası Üyesi
Rapor Teslim Tarihi: 15.04.2025
Ekler: Cari hesap mutabakat cetveli ve yevmiye özetleri.
"""

    karar = f"""# T.C. İSTANBUL ANADOLU 4. ASLİYE TİCARET MAHKEMESİ
## GEREKÇELİ KARAR

**MAHKEME:** İstanbul Anadolu 4. Asliye Ticaret Mahkemesi
**ESAS NO:** 2025/520 E.
**KARAR NO:** 2025/701 K.
**BAŞKAN:** Başkan Hâkim Orhan Çetin
**ÜYE HÂKİM:** Hâkim Sibel Kaya
**KATİP:** Zabıt Kâtibi Tuna Aksoy
**TARİH:** 22.05.2025

**DAVACI:** Atlas Makina Sanayi ve Ticaret A.Ş. (VKN: 1090456789)
**VEKİLİ:** Av. Berkay Demirci

**DAVALI:** Bosphorus Metal İthalat İhracat Ltd. Şti. (VKN: 2080123456)
**VEKİLİ:** Av. Melis Kılıç

## GEREKÇE
Tarafların ticari defterleri üzerinde yapılan YMM bilirkişi incelemesinde,
davacının düzenlediği faturaların davalı defterlerinde kayıtlı olduğu ve
TTK m. 21 uyarınca süresinde itiraz edilmediği anlaşılmıştır.

## HÜKÜM
1. Davacı Atlas Makina Sanayi ve Ticaret A.Ş.'nin davasının KABULÜNE,
2. 1.240.000,00 TL alacağın dava tarihinden itibaren işleyecek avans faizi ile
   birlikte davalı Bosphorus Metal İthalat İhracat Ltd. Şti.'den tahsiline,
3. Yargılama giderleri ile nispi vekâlet ücretinin davalıdan tahsiline karar
   verildi.
4. Peşin alınan harcın mahsubu ile bakiye karar ve ilam harcının davalıdan
   tahsiline, kullanılmayan gider avansının karar kesinleştiğinde yatırana
   iadesine karar verildi.

## KANUN YOLU BİLGİSİ
Kararın tebliğinden itibaren iki hafta içinde İstanbul Bölge Adliye Mahkemesi
nezdinde istinaf kanun yolu açık olmak üzere oybirliği ile karar verildi.

Başkan Hâkim Orhan Çetin
Hâkim Sibel Kaya
Zabıt Kâtibi Tuna Aksoy
Karar Tarihi: 22.05.2025
UYAP Onay Kodu: KAR-2025-701
"""

    project_json = json.dumps(
        {
            "dosyaNo": "2025/520 E.",
            "mahkeme": "İstanbul Anadolu 4. Asliye Ticaret Mahkemesi",
            "taraflar": [
                {"sifat": "Davacı", "adSoyad": "Atlas Makina Sanayi ve Ticaret A.Ş.", "tur": "Tüzel Kişi"},
                {"sifat": "Davalı", "adSoyad": "Bosphorus Metal İthalat İhracat Ltd. Şti.", "tur": "Tüzel Kişi"},
                {"sifat": "Vekil", "adSoyad": "Av. Berkay Demirci"},
                {"sifat": "Vekil", "adSoyad": "Av. Melis Kılıç"},
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    return Senaryo(
        ad="10_ticari_alacak",
        baslik="Ticari Alacak (İki Şirket Taraf, Sıfır Gerçek Kişi)",
        dosyalar={
            "01_Dava_Dilekcesi.md": dava_dilekcesi,
            "02_Cevap_Dilekcesi.md": cevap_dilekcesi,
            "03_Ticari_Defter_Bilirkisi_Raporu.md": bilirkisi_raporu,
            "04_Gerekceli_Karar.md": karar,
            "uyap-project.json": project_json,
        },
        gizli=[iban_sirket, "Orhan Çetin", "Sibel Kaya", "Tuna Aksoy"],
        korunan=[
            "Atlas Makina Sanayi ve Ticaret A.Ş.",
            "Bosphorus Metal İthalat İhracat Ltd. Şti.",
            "1090456789", "2080123456",
            "0109045678900011", "0208012345600019",
            "atlasmakina@hs02.kep.tr", "bosphorus@hs01.kep.tr", "muhasebe@atlasmakina.com.tr",
            "0216 555 88 99",
            "Organize Sanayi Sitesi 3. Blok No: 12 Tuzla/İstanbul",
            "Liman Yolu Caddesi No: 45 Gebze/Kocaeli",
            "Av. Berkay Demirci", "Av. Melis Kılıç",
            "Bilirkişi YMM Kerem Savaş",
            "İstanbul Anadolu 4. Asliye Ticaret Mahkemesi",
            "1.240.000,00 TL", "TTK m. 21",
        ],
        kisiler={
            "Orhan Çetin": "HAKİM",
            "Sibel Kaya": "HAKİM",
            "Tuna Aksoy": "KÂTİP",
        },
        ayni_etiket=[[iban_sirket]],
    )


# ---------------------------------------------------------------------------
# Senaryo 11: İdari Dava / İptal
# ---------------------------------------------------------------------------
def _build_senaryo_11() -> Senaryo:
    tc_davaci = _make_tckn("165432189")
    sicil_memur = "884120"

    dava_dilekcesi = f"""# ANKARA 9. İDARE MAHKEMESİ BAŞKANLIĞINA

**MAHKEME:** Ankara 9. İdare Mahkemesi
**ESAS NO:** 2025/318 E.
**TARİH:** 04.02.2025

**DAVACI:** Turgut Eren (T.C. Kimlik No: {tc_davaci})
**KURUM SİCİL NO:** {sicil_memur}
**ADRES:** Karanfil Sokak No: 25/8 Çankaya/Ankara
**CEP TEL:** 0534 210 98 76
**VEKİLİ:** Av. Furkan Yılmaz

**DAVALI:** T.C. Sağlık Bakanlığı
**ADRES:** Bilkent Yerleşkesi Üniversiteler Mahallesi Dumlupınar Bulvarı No: 9 Çankaya/Ankara

**KONU:** 657 sayılı DMK m. 125 uyarınca verilen aylıktan kesme disiplin cezasının
2577 sayılı İYUK kapsamında iptali talebidir.

## AÇIKLAMALAR
1. Davacı Turgut Eren, Ankara İl Sağlık Müdürlüğü bünyesinde {sicil_memur}
   sicil numarası ile şube müdürü olarak görev yapmaktadır.
2. Davalı T.C. Sağlık Bakanlığı tarafından düzenlenen soruşturma neticesinde
   hukuka aykırı biçimde aylıktan kesme cezası tesis edilmiştir.
3. Savunma süresi 657 sayılı DMK m. 130'a aykırı şekilde kısaltılmış, objektif
   deliller toplanmadan karar verilmiştir.
4. İşlem sebep, konu ve maksat unsurları bakımından hukuka aykırıdır.

## HUKUKİ SEBEPLER
2577 sayılı İYUK, 657 sayılı DMK m. 125, m. 130 ve Anayasa ilgili hükümleri.

## DELİLLER
1. Özlük dosyası ve idari soruşturma raporu,
2. Tanık beyanları,
3. Kurum yazışmaları.

## SONUÇ VE İSTEM
Hukuka aykırı disiplin cezasının iptaline ve kesilen tutarın yasal faiziyle
iadesine karar verilmesini arz ederim.

Davacı Vekili
Av. Furkan Yılmaz
"""

    savunma = f"""# ANKARA 9. İDARE MAHKEMESİ BAŞKANLIĞINA

**MAHKEME:** Ankara 9. İdare Mahkemesi
**ESAS NO:** 2025/318 E.
**TARİH:** 07.03.2025

**SAVUNMA VEREN DAVALI:** T.C. Sağlık Bakanlığı
**KURUM ADRESİ:** Bilkent Yerleşkesi Üniversiteler Mahallesi Dumlupınar Bulvarı No: 9 Çankaya/Ankara
**İLGİLİ BİRİM:** Ankara İl Sağlık Müdürlüğü (Sabit Tel: 0312 555 20 00)

**DAVACI:** Turgut Eren (TCKN: {tc_davaci}, Kurum Sicil No: {sicil_memur})
**VEKİLİ:** Av. Furkan Yılmaz

## USULE İLİŞKİN BEYANLAR
Dava konusu işlemin tebliğ tarihi ile dava açma süresi yönünden 2577 sayılı İYUK
m. 7 kapsamında re'sen inceleme yapılması talep edilmektedir.

## ESASA İLİŞKİN SAVUNMA BEYANLARIMIZ
1. Davacı Turgut Eren hakkında yürütülen disiplin soruşturması 657 sayılı DMK m. 125
   hükümlerine tamamen uygundur.
2. Ankara İl Sağlık Müdürlüğü kayıtlarına göre davacıya yedi günlük savunma
   hakkı usulüne uygun olarak tebliğ edilmiştir.
3. İhale komisyon tutanağındaki usulsüzlük idare bütünlüğünü zedelemiştir.
4. 2577 sayılı İYUK kapsamında hukuka uygun tesis edilen işlemin iptalini
   gerektirir bir sebep bulunmadığından davanın reddi talep olunur.

## EKLER
- Soruşturma onay belgesi ve ifade tutanakları,
- Savunma istem yazısı ve tebellüğ belgesi,
- Özlük sicil özeti ve görevlendirme yazısı.

## SONUÇ VE TALEP
Yukarıda açıklanan nedenlerle hukuka uygun disiplin cezasının iptali
talebinin reddi ile yargılama giderlerinin davacıya yükletilmesine karar
verilmesini arz ederiz.

T.C. Sağlık Bakanlığı Hukuk Müşavirliği
Av. Gülşah Özer
Savunma Sunum Tarihi: 07.03.2025
KEP Adresi: saglikhukuk@hs01.kep.tr
Sabit Hat: 0312 555 21 00
"""

    sorusturma = f"""# T.C. SAĞLIK BAKANLIĞI TEFTİŞ KURULU BAŞKANLIĞI
## İDARİ SORUŞTURMA ÖZET BELGESİ

**DOSYA NO:** 2024/1190-SOR
**İLGİLİ MAHKEME:** Ankara 9. İdare Mahkemesi (2025/318 E.)
**KURUM ADRESİ:** Bilkent Yerleşkesi Üniversiteler Mahallesi Dumlupınar Bulvarı No: 9 Çankaya/Ankara
**MUHAKKİK:** Başmüfettiş Kemalettin Arslan
**TARİH:** 12.12.2024

**HAKKINDA SORUŞTURMA YAPILAN:** Turgut Eren
- **T.C. Kimlik No:** {tc_davaci}
- **Memur Sicil No:** {sicil_memur}
- **İkamet Adresi:** Karanfil Sokak No: 25/8 Çankaya/Ankara
- **Cep Telefonu:** 0534 210 98 76

## İNCELEME TESPİTLERİ
1. Ankara İl Sağlık Müdürlüğü evrak kayıtlarının incelenmesinde; görevli memur
   Turgut Eren ({sicil_memur}) tarafından düzenlenen 14.10.2024 tarihli ihale
   komisyon tutanağında şekli eksiklik tespit edilmiştir.
2. Ancak ihale bedelinde veya kamu kaynağında herhangi bir kamu zararı
   doğmadığı mali denetim raporunda açıkça kayda geçirilmiştir.
3. İlgilinin önceki sicil notlarının olumlu olduğu ve daha önce disiplin
   cezası almadığı özlük dosyasından görülmüştür.

## ÖNERİ
657 sayılı DMK m. 125 uyarınca alt ceza uygulanması hususu makamın takdirine
sunulmuştur.

## İLGİLİ BİRİM VE EKLER
- İnceleme Birimi: Ankara İl Sağlık Müdürlüğü Teftiş Bürosu
- Sabit Hat: 0312 555 20 00
- Ek 1: 14.10.2024 tarihli ihale komisyon tutanağı
- Ek 2: Mali denetim inceleme raporu
- Ek 3: Görevli memur savunma metni
- Ek 4: Özlük dosyası sicil özet tablosu

Başmüfettiş Kemalettin Arslan
Tarih: 12.12.2024
Onay: Teftiş Kurulu Başkanlığı
Evrak Kayıt No: TEF-2024-1190
"""

    karar = f"""# T.C. ANKARA 9. İDARE MAHKEMESİ
## KARAR

**MAHKEME:** Ankara 9. İdare Mahkemesi
**ESAS NO:** 2025/318 E.
**KARAR NO:** 2025/590 K.
**TARİH:** 29.04.2025

**BAŞKAN:** Başkan Hâkim Sevilay Aksoy
**ÜYE HÂKİM:** Üye Hâkim Engin Kaya
**ÜYE HÂKİM:** Üye Hâkim Deniz Özkan

**DAVACI:** Turgut Eren (TCKN: {tc_davaci})
**VEKİLİ:** Av. Furkan Yılmaz
**DAVALI:** T.C. Sağlık Bakanlığı

## OLAY VE HUKUKİ DEĞERLENDİRME
Dosyadaki bilgi ve belgelerin incelenmesinden; {sicil_memur} sicil numaralı davacı
Turgut Eren'in eyleminin 657 sayılı DMK m. 125/C kapsamında ağırlığı ile orantılı
olmadığı, savunma hakkının kısıtlandığı ve kamu zararı bulunmadığı anlaşılmıştır.

## HÜKÜM
1. Dava konusu aylıktan kesme disiplin cezası işleminin İPTALİNE 2577 sayılı İYUK
   uyarınca oybirliği ile karar verildi.
2. Kesilen maaş tutarının idarece davacıya iadesine,
3. Yargılama giderlerinin davalı idare üzerinde bırakılmasına karar verildi.
4. AAÜT uyarınca belirlenen vekâlet ücretinin davalı idareden alınarak davacıya
   verilmesine karar verildi.

## KANUN YOLU
İşbu karara karşı tebliğ tarihini izleyen otuz gün içinde Ankara Bölge İdare
Mahkemesi nezdinde istinaf yolu açıktır.

Başkan Hâkim Sevilay Aksoy
Üye Hâkim Engin Kaya
Üye Hâkim Deniz Özkan
Zabıt Kâtibi Murat Yılmaz
Karar Tarihi: 29.04.2025
UYAP Evrak Doğrulama: IDARE-2025-590
Tebliğ Şerhi: Taraflara elektronik tebligat ile gönderilmiştir.
"""

    project_json = json.dumps(
        {
            "dosyaNo": "2025/318 E.",
            "mahkeme": "Ankara 9. İdare Mahkemesi",
            "taraflar": [
                {"sifat": "Davacı", "adSoyad": "Turgut Eren", "tckn": tc_davaci},
                {"sifat": "Davalı", "adSoyad": "T.C. Sağlık Bakanlığı", "tur": "Kamu Kurumu"},
                {"sifat": "Vekil", "adSoyad": "Av. Furkan Yılmaz"},
            ],
        },
        ensure_ascii=False,
        indent=2,
    )

    return Senaryo(
        ad="11_idari_dava_iptal",
        baslik="İdari Dava / İptal (Memur Sicil + Kurum Adresleri)",
        dosyalar={
            "Dilekceler/Davaci_Turgut_Eren_Dava_Dilekcesi.md": dava_dilekcesi,
            "02_Idare_Savunma_Dilekcesi.md": savunma,
            "03_Idari_Sorusturma_Ozet_Belgesi.md": sorusturma,
            "04_Idare_Mahkemesi_Karari.md": karar,
            "uyap-project.json": project_json,
        },
        gizli=[
            tc_davaci, sicil_memur,
            "0534 210 98 76",
            "Karanfil Sokak No: 25/8",
            "Turgut Eren", "Turgut_Eren",
            "Sevilay Aksoy", "Engin Kaya", "Deniz Özkan", "Murat Yılmaz",
        ],
        korunan=[
            "T.C. Sağlık Bakanlığı",
            "Ankara İl Sağlık Müdürlüğü",
            "Bilkent Yerleşkesi Üniversiteler Mahallesi Dumlupınar Bulvarı No: 9 Çankaya/Ankara",
            "Ankara 9. İdare Mahkemesi",
            "2577 sayılı İYUK",
            "657 sayılı DMK m. 125",
            "Av. Furkan Yılmaz",
            "0312 555 20 00",
        ],
        kisiler={
            "Turgut Eren": "DAVACI",
            "Sevilay Aksoy": "HAKİM",
            "Engin Kaya": "HAKİM",
            "Deniz Özkan": "HAKİM",
            "Murat Yılmaz": "KÂTİP",
        },
        ayni_etiket=[
            [tc_davaci],
            [sicil_memur],
            ["Turgut Eren"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 12: Çok Taraflı Tapu İptal-Tescil (8+ davalı, aynı baş harf, orta ad, SOYAD Ad)
# ---------------------------------------------------------------------------
def _build_senaryo_12() -> Senaryo:
    tcs = {
        "ibrahim": _make_tckn("102938475"),
        "fatma": _make_tckn("203948576"),
        "mehmet": _make_tckn("304958677"),
        "ahmet": _make_tckn("405968778"),
        "ali": _make_tckn("506978879"),
        "hatice": _make_tckn("607988971"),
        "suleyman": _make_tckn("708998172"),
        "naciye": _make_tckn("809108273"),
        "osman": _make_tckn("901218374"),
        "zubeyde": _make_tckn("112328475"),
        "tanik": _make_tckn("223438576"),
    }

    dava_dilekcesi = f"""# ANTALYA 3. ASLİYE HUKUK MAHKEMESİNE

**MAHKEME:** Antalya 3. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/610 E.
**TARİH:** 11.02.2025

**DAVACI:** İbrahim Korkmaz (TCKN: {tcs['ibrahim']})
**ADRES:** Güllük Caddesi No: 34/5 Muratpaşa/Antalya
**VEKİLİ:** Av. Zafer Öztürk

**DAVALILAR:**
1- Fatma Zehra Korkmaz (TCKN: {tcs['fatma']}) - Adres: Fener Sokak No: 2/1 Muratpaşa/Antalya
2- Mehmet Emin Korkmaz (TCKN: {tcs['mehmet']}) - Adres: Lara Caddesi No: 18/3 Muratpaşa/Antalya
3- Ahmet Özdemir (TCKN: {tcs['ahmet']}) - Adres: Konyaaltı Sokak No: 7/4 Konyaaltı/Antalya
4- Ali Özdemir (TCKN: {tcs['ali']}) - Adres: Uncalı Caddesi No: 12/2 Konyaaltı/Antalya
5- Hatice Öztürk (TCKN: {tcs['hatice']}) - Adres: Varsak Sokak No: 5/9 Kepez/Antalya
6- Süleyman Öztürk (TCKN: {tcs['suleyman']}) - Adres: Sütçüler Caddesi No: 21/1 Kepez/Antalya
7- Naciye Şimşek (TCKN: {tcs['naciye']}) - Adres: Meltem Sokak No: 9/6 Muratpaşa/Antalya
8- Osman Şimşek (TCKN: {tcs['osman']}) - Adres: Kırcami Caddesi No: 40/8 Muratpaşa/Antalya
9- Zübeyde Aslan (TCKN: {tcs['zubeyde']}) - Adres: Hurma Sokak No: 11/2 Konyaaltı/Antalya

**KONU:** Muris muvazaası nedeniyle 412 Ada 7 Parsel sayılı taşınmazın tapu kaydının
iptali ile davacı adına tescili talebidir.

## AÇIKLAMALAR
1. Davacı İbrahim Korkmaz ile davalılar Fatma Zehra Korkmaz ve Mehmet Emin Korkmaz
   aynı kökten mirasçılardır.
2. Diğer davalılar Ahmet Özdemir, Ali Özdemir, Hatice Öztürk, Süleyman Öztürk,
   Naciye Şimşek, Osman Şimşek ve Zübeyde Aslan ise taşınmazın sonraki el
   değiştirmelerinde kayıt maliki görünen üçüncü kişilerdir.
3. İşlemin gerçek bir satış olmadığı tanık Hüseyin Yücel (Tel: 0532 612 34 56)
   beyanı ile ispatlanacaktır.
4. Muratpaşa Tapu Müdürlüğü kayıtlarında yer alan resmi senetlerin celbi talep olunur.

## DELİLLER
- Tapu kayıtları ve veraset ilamı,
- Keşif, bilirkişi incelemesi ve tanık beyanı.

Davacı Vekili
Av. Zafer Öztürk
"""

    tapu_kaydi = f"""# MURATPAŞA TAPU MÜDÜRLÜĞÜ
## TAPU KAYDI VE KADASTRO BİLGİ YAZISI

**DÜZENLEYEN KURUM:** Muratpaşa Tapu Müdürlüğü
**KURUM ADRESİ:** Bayındır Mahallesi Gazi Bulvarı No: 64 Muratpaşa/Antalya
**İLGİ:** Antalya 3. Asliye Hukuk Mahkemesi 2025/610 E.
**TAŞINMAZ:** Antalya İli Muratpaşa İlçesi 412 Ada 7 Parsel
**TARİH:** 21.02.2025

## AKTİF VE PASİF MALİK LİSTESİ (SOYAD AD SIRALI)
- KORKMAZ İbrahim (TCKN: {tcs['ibrahim']}) - Davacı / Mirasçı
- KORKMAZ Fatma Zehra (TCKN: {tcs['fatma']}) - Hisse: 1/9
- KORKMAZ Mehmet Emin (TCKN: {tcs['mehmet']}) - Hisse: 1/9
- ÖZDEMİR Ahmet (TCKN: {tcs['ahmet']}) - Hisse: 1/9
- ÖZDEMİR Ali (TCKN: {tcs['ali']}) - Hisse: 1/9
- ÖZTÜRK Hatice (TCKN: {tcs['hatice']}) - Hisse: 1/9
- ÖZTÜRK Süleyman (TCKN: {tcs['suleyman']}) - Hisse: 1/9
- ŞİMŞEK Naciye (TCKN: {tcs['naciye']}) - Hisse: 1/9
- ŞİMŞEK Osman (TCKN: {tcs['osman']}) - Hisse: 1/9
- ASLAN Zübeyde (TCKN: {tcs['zubeyde']}) - Hisse: 1/9

## EDİNME SEBEBİ VE ŞERHLER
1. Taşınmaz 412 Ada 7 Parsel üzerinde Antalya 3. Asliye Hukuk Mahkemesi
   2025/610 E. sayılı dosyası üzerinden ihtiyati tedbir şerhi işlenmiştir.
2. 15.05.2019 tarihli satış akdi resmi senetleri ile 22.08.2021 tarihli
   intikal belgeleri ekli olarak mahkemenize gönderilmiştir.
3. Taşınmaz üzerinde başkaca ipotek veya haciz kaydı bulunmamaktadır.
4. Kadastro pafta ve çap örneği ile zemin alan ölçüm cetveli yazımız ekinde
   sunulmuştur.
5. Taşınmazın yüzölçümü 2.450,00 m2 olup tarla/arsa vasfından imarlı arsa
   vasfına dönüştürülmüştür.

## İRTİBAT BİLGİLERİ
- Kurum: Muratpaşa Tapu Müdürlüğü
- Sabit Telefon: 0242 310 22 00
- KEP Adresi: muratpasatapu@hs01.kep.tr

Tapu Sicil Müdürü
Mustafa Aydın
Muratpaşa Tapu Müdürlüğü
"""

    tensip_taraf = f"""# ANTALYA 3. ASLİYE HUKUK MAHKEMESİ
## TENSİP VE TARAF TEŞKİLİ ZAPTI

**MAHKEME:** Antalya 3. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/610 E.
**HAKİM:** Hâkim Gülten Şahin
**KATİP:** Zabıt Kâtibi Emine Tunç
**TARİH:** 28.02.2025

**DAVACI:** İbrahim Korkmaz - Vekili: Av. Zafer Öztürk
**DAVALILAR:** Fatma Zehra Korkmaz, Mehmet Emin Korkmaz, Ahmet Özdemir, Ali Özdemir,
Hatice Öztürk, Süleyman Öztürk, Naciye Şimşek, Osman Şimşek, Zübeyde Aslan.

## ARA KARARLAR
1. Yargılamanın HMK yazılı yargılama usulüne tabi olarak yürütülmesine,
2. Tüm davalılara dava dilekçesi ekli tebligat çıkarılmasına; Ahmet Özdemir
   (TCKN: {tcs['ahmet']}) ile Ali Özdemir (TCKN: {tcs['ali']}) isimli davalıların
   adreslerinin karışmaması için ayrı ayrı tebligat düzenlenmesine,
3. Davalı Fatma Zehra Korkmaz vekili Av. Deniz Yılmaz'ın vekâletnamesinin dosyaya
   kabulüne,
4. Muratpaşa Tapu Müdürlüğü nezdindeki 412 Ada 7 Parsel tapu kütüğünün celbine,
5. Davacı tanığı Hüseyin Yücel için duruşma davetiyesi çıkarılmasına,
6. Taraf teşkilinin tamamlanmasının ardından ön inceleme gününün belirlenmesine
   karar verildi.

## TEBLİGAT KONTROL LİSTESİ
- Davalı Mehmet Emin Korkmaz: Tebligat çıkarıldı.
- Davalı Hatice Öztürk ve Süleyman Öztürk: Tebligat çıkarıldı.
- Davalı Naciye Şimşek, Osman Şimşek, Zübeyde Aslan: Tebligat çıkarıldı.
- Davalı Fatma Zehra Korkmaz: Vekili Av. Deniz Yılmaz'a elektronik tebligat yapıldı.
- Davalı Ahmet Özdemir ve Ali Özdemir: MERNİS adreslerine ayrı ayrı çıkarıldı.

## ÖN İNCELEME TAKVİMİ
Taraf teşkili tamamlandıktan sonra HMK m. 139 gereğince ön inceleme duruşma
günü taraflara ayrıca tebliğ edilecektir.

Hâkim Gülten Şahin
Zabıt Kâtibi Emine Tunç
Tensip Düzenleme Tarihi: 28.02.2025
UYAP Duruşma Hazırlık Kaydı: 2025/610-TNS
"""

    tanik_tutanak = f"""# ANTALYA 3. ASLİYE HUKUK MAHKEMESİ
## TANIK DİNLEME TUTANAĞI

**MAHKEME:** Antalya 3. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/610 E.
**DURUŞMA TARİHİ:** 10.04.2025
**HAKİM:** Hâkim Gülten Şahin
**KATİP:** Zabıt Kâtibi Emine Tunç

**TANIK:** Hüseyin Yücel (T.C. Kimlik No: {tcs['tanik']})
**TEL:** 0532 612 34 56
**ADRES:** Demircikara Sokak No: 8/3 Muratpaşa/Antalya

Tanığa HMK m. 258 uyarınca yemini yaptırıldı. Taraflarla akrabalık bağı
olmadığı ancak köyden komşu olduğu anlaşıldı.

## TANIK BEYANI
"Ben tarafların köyünden uzun yıllardır komşusuyum. İbrahim Korkmaz ile kardeşleri
Fatma Zehra Korkmaz ve Mehmet Emin Korkmaz arasındaki tartışmaları bilirim.
Babaları sağlığında 412 Ada 7 Parsel sayılı araziyi kardeşler arasında
paylaştırmıştı ancak tapu devrinde Ahmet Özdemir ve Ali Özdemir üzerinden
göstermelik satış işlemi yapıldığını duydum. Hatice Öztürk, Süleyman Öztürk,
Naciye Şimşek, Osman Şimşek ve Zübeyde Aslan da gerçek bir satış bedeli
ödendiğini görmediklerini konuşurlardı. Bildiklerim bundan ibarettir."

## TARAF VEKİLLERİ BEYANI
- Davacı Vekili Av. Zafer Öztürk: "Tanık beyanını kabul ediyoruz."
- Davalı Vekili Av. Deniz Yılmaz: "Tanık duyuma dayalı beyanda bulunmuştur, kabul etmiyoruz."

## DURUŞMA SONU KARARI
1. Tanık beyanlarına karşı beyanda bulunmak üzere taraf vekillerine iki hafta
   süre verilmesine,
2. Gelecek celsenin 29.05.2025 günü saat 10:00'da yapılmasına karar verildi.

Tanık beyanı imzalandı.
Tanık: Hüseyin Yücel
Hâkim Gülten Şahin
Zabıt Kâtibi Emine Tunç
Tensip Düzenleme Tarihi: 28.02.2025
UYAP Duruşma Hazırlık Kaydı: 2025/610-TNS
"""

    return Senaryo(
        ad="12_cok_tarafli_tapu_iptal",
        baslik="Çok Taraflı Tapu İptal-Tescil (10 Davalı/Tanık, Orta Ad, SOYAD Ad)",
        dosyalar={
            "01_Dava_Dilekcesi.md": dava_dilekcesi,
            "02_Tapu_Kaydi_ve_Kadastro_Yazisi.md": tapu_kaydi,
            "03_Tensip_ve_Taraf_Teskil_Zapti.md": tensip_taraf,
            "04_Tanik_Dinleme_Tutanagi.md": tanik_tutanak,
        },
        gizli=[
            *tcs.values(),
            "0532 612 34 56",
            "Güllük Caddesi No: 34/5", "Fener Sokak No: 2/1", "Lara Caddesi No: 18/3",
            "Konyaaltı Sokak No: 7/4", "Uncalı Caddesi No: 12/2", "Varsak Sokak No: 5/9",
            "Sütçüler Caddesi No: 21/1", "Meltem Sokak No: 9/6", "Kırcami Caddesi No: 40/8",
            "Hurma Sokak No: 11/2", "Demircikara Sokak No: 8/3",
            "İbrahim Korkmaz", "KORKMAZ İbrahim",
            "Fatma Zehra Korkmaz", "KORKMAZ Fatma Zehra",
            "Mehmet Emin Korkmaz", "KORKMAZ Mehmet Emin",
            "Ahmet Özdemir", "ÖZDEMİR Ahmet",
            "Ali Özdemir", "ÖZDEMİR Ali",
            "Hatice Öztürk", "ÖZTÜRK Hatice",
            "Süleyman Öztürk", "ÖZTÜRK Süleyman",
            "Naciye Şimşek", "ŞİMŞEK Naciye",
            "Osman Şimşek", "ŞİMŞEK Osman",
            "Zübeyde Aslan", "ASLAN Zübeyde",
            "Hüseyin Yücel",
            "Gülten Şahin", "Emine Tunç",
        ],
        korunan=[
            "Antalya 3. Asliye Hukuk Mahkemesi",
            "412 Ada 7 Parsel",
            "Av. Zafer Öztürk",
            "Av. Deniz Yılmaz",
            "Muratpaşa Tapu Müdürlüğü",
            "Bayındır Mahallesi Gazi Bulvarı No: 64 Muratpaşa/Antalya",
        ],
        kisiler={
            "İbrahim Korkmaz": "DAVACI",
            "Fatma Zehra Korkmaz": "DAVALI",
            "Mehmet Emin Korkmaz": "DAVALI",
            "Ahmet Özdemir": "DAVALI",
            "Ali Özdemir": "DAVALI",
            "Hatice Öztürk": "DAVALI",
            "Süleyman Öztürk": "DAVALI",
            "Naciye Şimşek": "DAVALI",
            "Osman Şimşek": "DAVALI",
            "Zübeyde Aslan": "DAVALI",
            "Hüseyin Yücel": "TANIK",
            "Gülten Şahin": "HAKİM",
            "Emine Tunç": "KÂTİP",
        },
        ayni_etiket=[
            ["Fatma Zehra Korkmaz", "KORKMAZ Fatma Zehra"],
            ["Ahmet Özdemir", "ÖZDEMİR Ahmet"],
            ["Ali Özdemir", "ÖZDEMİR Ali"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 13: Bozuk Biçim / OCR Benzeri Metin
# ---------------------------------------------------------------------------
def _build_senaryo_13() -> Senaryo:
    tc_davaci = _make_tckn("141414141")
    tc_davali = _make_tckn("252525252")
    iban_davaci = _make_iban("00062", "0012345678901234")
    iban_p1 = iban_davaci[:14]
    iban_p2 = iban_davaci[14:]

    ocr_dilekce = (
        "# ANKARA 2. ASLIYE HUKUK MAHKEMESINE\n\n"
        "ESAS NO: 2025/77 E.\n"
        "TARIH: 08.01.2025\n\n"
        f"DAVACI:\u00a0HAKAN\u00a0YILMAZ\u00a0\u00a0(TCKN:\u00a0{tc_davaci})\n"
        "ADRES:  Mustafa Kemal Mah.  Menekse Sokak No: 15/2\n"
        "Cankaya / Ankara\n"
        "TELEFON: 0 (532) 111-22-33\n"
        "VEKILI: Av. Deniz Aksoy\n\n"
        f"DAVALI:  GIZEM SAHIN  (TCKN: {tc_davali})\n"
        "ADRES: Bahcelievler Mah. Sedef Cad. No: 9/4 Cankaya/Ankara\n"
        "CEP GSM: +90 541 222 33 44\n\n"
        "KONU:  SEBEPSIZ ZENGINLESME NEDENIYLE 55.000,00 TL ALACAK TALEBIDIR.\n\n"
        "ACIKLAMALAR:\n"
        "1. Davaci Hakan Yilmaz tarafindan davali Gizem Sahin hesabina yanlislikla\n"
        "gonderilen 55.000,00 TL bedelin iadesi talep edilmektedir.\n"
        "2. Iade yapilacak IBAN Numarasi:\n"
        f"{iban_p1}\n"
        f"{iban_p2}\n"
        "3. Irtibat numarasi +90 532 111 22 33 olup tebligatlarin vekile yapilmasi\n"
        "talep olunur.\n"
        "4. Ankara 2. Asliye Hukuk Mahkemesi 2025/77 E. sayili dosyasi kapsaminda\n"
        "delillerimiz ekte sunulmustur.\n"
        "5. Taraflar arasinda yazili sozlesme bulunmamaktadir.\n"
        "6. Ihtarname 12.12.2024 tarihinde keside edilmistir.\n"
        "7. Davali taraf ihtara cevap vermemistir.\n"
        "8. Banka dekontu ekte sunulmustur.\n"
        "9. Yargilama giderlerinin davalidan tahsili talep edilir.\n"
        "10. Davaci Hakan Yilmaz vekili olarak saygilarimizla arz ederiz.\n\n"
        "Hukuki Nedenler: TBK m. 77 vd.\n"
        "Deliller: Banka dekontu, ihtarname, tanik.\n"
        "Sonuc: Davanin kabulune karar verilmesi talep olunur.\n\n"
        "Davaci Vekili\n"
        "Av. Deniz Aksoy\n"
        "Tarih: 08.01.2025\n"
        "Ek: Banka dekontu sureti\n"
        "Sayfa 1 / 1\n"
    )

    tablo_bilgi = f"""# TARAF KİMLİK VE İLETİŞİM TABLOSU (OCR AKTARIM)

**DOSYA:** Ankara 2. Asliye Hukuk Mahkemesi - 2025/77 E.
**TARİH:** 15.01.2025

| Rol | Ad Soyad | TCKN | Telefon | Adres |
|---|---|---|---|---|
| Davacı | Hakan Yılmaz | {tc_davaci} | 05321112233 | Menekşe Sokak No: 15/2 Çankaya/Ankara |
| Davalı | Gizem Şahin | {tc_davali} | 05412223344 | Sedef Cad. No: 9/4 Çankaya/Ankara |

## EK BİLGİLER
- Davacı IBAN (Bitişik): {iban_davaci}
- Davacı Cep (Parantezli): 0 (532) 111-22-33
- Davalı Cep (Uluslararası): +90 541 222 33 44
- Davacı Vekili: Av. Deniz Aksoy

## NOTLAR
1. İşbu tablo taranmış belgelerden OCR ile elde edilen kayıtların özetidir.
2. Davacı adı büyük harf ve aksansız belgelerde HAKAN YILMAZ ve Hakan Yilmaz
   olarak da geçmektedir.
3. Davalı adı aksansız belgelerde GIZEM SAHIN biçiminde taranmıştır.
4. Talep tutarı 55.000,00 TL olup TBK m. 77 hükümleri uygulanacaktır.
5. Duruşma günü henüz belirlenmemiştir.
6. Mahkeme kalemi tarafından dosya ön incelemeye alınmıştır.
7. Davacı taraf harç ve gider avansını yatırmıştır.
8. Tebligat mazbataları beklenmektedir.
9. Taraf adresleri Mernis üzerinden teyit edilecektir.
10. Banka cevabı celp edilecektir.
11. Bilirkişi incelemesi gerekip gerekmediği ön incelemede değerlendirilecektir.
12. Faiz başlangıç tarihi ihtar temerrüt tarihidir.
13. Vekâletname aslı dosyadadır.
14. Harç makbuzu ektedir.
15. Avukatlık ücreti talebi saklıdır.
16. İhtiyati tedbir talebi yoktur.
17. Delil listesi süresi içinde sunulacaktır.
18. Cevap süresi iki haftadır.
19. Elektronik tebligat adresi bildirilmiştir.
20. Dosya kapağı kontrol edilmiştir.
21. Evrak taraması tamamlanmıştır.
22. Son kontrol tarihi: 15.01.2025.
"""

    duzeltilmis_tutanak = f"""# ANKARA 2. ASLİYE HUKUK MAHKEMESİ
## ÖN İNCELEME DURUŞMA TUTANAĞI

**MAHKEME:** Ankara 2. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/77 E.
**TARİH:** 20.03.2025
**HAKİM:** Hâkim Kemalettin Kaya
**KATİP:** Zabıt Kâtibi Yasemin Çelik

**DAVACI:** Hakan Yılmaz (T.C. Kimlik No: {tc_davaci})
**ADRES:** Menekşe Sokak No: 15/2 Çankaya/Ankara
**TEL:** +90 532 111 22 33
**VEKİLİ:** Av. Deniz Aksoy

**DAVALI:** Gizem Şahin (T.C. Kimlik No: {tc_davali})
**ADRES:** Sedef Cad. No: 9/4 Çankaya/Ankara
**TEL:** 0541 222 33 44

## TUTANAK
1. Davacı Hakan Yılmaz vekili Av. Deniz Aksoy duruşmaya katıldı, dava dilekçesini
   tekrar etti.
2. Davalı Gizem Şahin duruşmaya bizzat katıldı, 55.000,00 TL tutarındaki ödemeyi
   iade edeceğini ancak taksit talep ettiğini beyan etti.
3. Ödemenin davacıya ait {iban_davaci} numaralı IBAN hesabına yapılması hususu
   tutanağa geçirildi.
4. Taraflara sulh görüşmeleri için 2 hafta süre verilmesine, duruşmanın
   17.04.2025 günü saat 09:45'e bırakılmasına karar verildi.

Hâkim Kemalettin Kaya
Zabıt Kâtibi Yasemin Çelik
Davacı Vekili: Av. Deniz Aksoy
Davalı: Gizem Şahin

## EK KAYITLAR
- Dosya durumu: Ön inceleme tamamlandı.
- Uyuşmazlık konusu: Sebepsiz zenginleşme (55.000,00 TL).
- Dava tarihi: 08.01.2025.
- Harç durumu: Tamam.
- Tanık bildirimi: Yok.
- Bilirkişi: Gerek görülmedi.
- Tebligat: Tamam.
- Ara karar sayısı: 4.
"""

    return Senaryo(
        ad="13_bozuk_bicim_ocr",
        baslik="Bozuk Biçim / OCR Benzeri Metin (ALL CAPS, Aksansız, NBSP, Bölünmüş)",
        dosyalar={
            "01_Taranmis_Dilekce_OCR.md": ocr_dilekce,
            "02_Ek_Tablo_Bilgileri.md": tablo_bilgi,
            "03_Duzeltilmis_Tutanak.md": duzeltilmis_tutanak,
        },
        gizli=[
            tc_davaci, tc_davali, iban_davaci,
            "0 (532) 111-22-33", "+90 532 111 22 33", "05321112233",
            "+90 541 222 33 44", "05412223344", "0541 222 33 44",
            "Menekşe Sokak No: 15/2", "Menekse Sokak No: 15/2",
            "Sedef Cad. No: 9/4",
            "Hakan Yılmaz", "Hakan Yilmaz", "HAKAN YILMAZ", "HAKAN\u00a0YILMAZ",
            "Gizem Şahin", "GIZEM SAHIN",
            "Kemalettin Kaya", "Yasemin Çelik",
        ],
        korunan=[
            "Av. Deniz Aksoy",
            "Ankara 2. Asliye Hukuk Mahkemesi",
            "2025/77 E.",
            "55.000,00 TL",
        ],
        kisiler={
            "Hakan Yılmaz": "DAVACI",
            "Gizem Şahin": "DAVALI",
            "Kemalettin Kaya": "HAKİM",
            "Yasemin Çelik": "KÂTİP",
        },
        ayni_etiket=[
            ["0 (532) 111-22-33", "+90 532 111 22 33", "05321112233"],
            ["+90 541 222 33 44", "05412223344", "0541 222 33 44"],
            ["Hakan Yılmaz", "Hakan Yilmaz"],
            ["Gizem Şahin", "GIZEM SAHIN"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 14: Yanıltıcı İçerik (False-Positive Tuzakları)
# ---------------------------------------------------------------------------
def _build_senaryo_14() -> Senaryo:
    tc_davaci = _make_tckn("181818181")
    tc_tanik = _make_tckn("292929292")
    barkod1 = _make_non_tckn("918273645")
    barkod2 = _make_non_tckn("271829384")

    dava_dilekcesi = f"""# ANKARA 7. ASLİYE HUKUK MAHKEMESİNE

**MAHKEME:** Ankara 7. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/12345
**KARAR NO:** 2025/67890
**EVRAK BARKOD NO:** {barkod1}
**PTT BARKOD:** {barkod2}

**DAVACI:** Ömer Faruk Akın (T.C. Kimlik No: {tc_davaci})
**ADRES:** Zambak Sokak No: 4/2 Çankaya/Ankara
**CEP TEL:** 0532 999 00 11
**VEKİLİ:** Av. Cemalettin Aydın

**DAVALI:** Ahmet Yılmaz İnşaat Ltd. Şti.
**ŞİRKET ADRESİ:** Mehmet Akif Ersoy Caddesi No: 100 Yenimahalle/Ankara

**KONU:** Eser sözleşmesinden kaynaklanan 125.400,00 TL tazminat talebidir.

## AÇIKLAMALAR
1. Davacı Ömer Faruk Akın, davalı Ahmet Yılmaz İnşaat Ltd. Şti. ile bir inşaat
   sözleşmesi imzalamıştır.
2. Olay günü İstiklal Caddesi ile Sakarya Sokak kesişimi noktasında şantiye
   alanında meydana gelen su baskını nedeniyle 125.400,00 TL zarar oluşmuştur.
3. Şantiye alanının hemen yanında Atatürk Anadolu Lisesi ve Dr. Sami Ulus Çocuk Hastanesi
   bulunmakta olup taşeron teslimatları Mustafa Kemal Mahallesi üzerinden yapılmıştır.
4. Bölge deniz kıyısında güneş batarken dahi yoğun rüzgar aldığından kaya ve demir malzemeler
   açıkta bırakılmamalıydı; işçiler barış ve özgür çalışma ortamı içinde güvenli
   şekilde çalışmalıydı.
5. Şirketin bu ihmali nedeniyle savaş mağduriyeti olmaksızın normal şartlarda
   bile beklenmeyecek bir zarar ortaya çıkmıştır.
6. Tanık Leyla Çınar (TCKN: {tc_tanik}) olay anına bizzat şahittir.

## DELİLLER
1. Evrak Barkod No: {barkod1} sayılı keşif tutanağı,
2. PTT Barkod: {barkod2} ile gönderilen ihtarname,
3. Tanık Leyla Çınar beyanı.

## SONUÇ VE İSTEM
Yukarıda arz edilen nedenlerle 125.400,00 TL tazminatın davalıdan tahsilini
vekaleten arz ederim.

Davacı Vekili
Av. Cemalettin Aydın
"""

    olay_raporu = f"""# ŞİRKET VE OLAY YERİ İNCELEME RAPORU

**MAHKEME:** Ankara 7. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/12345
**TARİH:** 10.03.2025

**DAVACI:** Ömer Faruk Akın (TCKN: {tc_davaci})
**VEKİLİ:** Av. Cemalettin Aydın
**DAVALI:** Ahmet Yılmaz İnşaat Ltd. Şti.
**VEKİLİ:** Av. Sinan Yıldız

## İNCELEME DETAYLARI
1. Şirket merkezi Mehmet Akif Ersoy Caddesi üzerinde olup Mustafa Kemal Mahallesi
   sınırları içerisindedir.
2. Olay yeri İstiklal Caddesi ile Sakarya Sokak kesişimi olarak kayda geçmiştir.
3. Yakın çevredeki Atatürk Anadolu Lisesi ile Dr. Sami Ulus Çocuk Hastanesi
   yapılarında herhangi bir hasar tespit edilmemiştir.
4. Teknik raporda kaya ve demir malzemeler ile toprak dolgusunun standartlara
   uygun olmadığı belirtilmiştir.
5. İnceleme bedeli 125.400,00 TL tutarındadır.
6. Deniz kıyısında güneş batarken yapılan ölçümlerde nem oranının yüksek olduğu,
   bölgedeki barış ve özgür çalışma ortamı kapsamında iş güvenliği tedbirlerinin
   artırılması gerektiği vurgulanmıştır.
7. PTT Barkod: {barkod2} ve Evrak Barkod No: {barkod1} belgeleri dosya içindedir.

## SONUÇ
Olay yerindeki drenaj yetersizliğinin hasara yol açtığı tespit edilmiştir.
Rapor iki nüsha halinde mahkeme kalemine sunulmuştur.
Olay yerindeki su tahliye kanallarının bakım eksikliği fotoğraflarla belgelenmiştir.
Şantiye çevresindeki yağmur suyu ızgaralarının kapalı olduğu görülmüştür.
Keşif sırasında çekilen 14 adet renkli fotoğraf rapor ekine konulmuştur.
Raporun taraflara tebliği mahkeme takdirindedir.
Teslim Kayıt No: BLR-2025-12345

Düzenleyen Bilirkişi: İnşaat Mühendisi Mehmet Kaya
Tarih: 10.03.2025
Oda Sicil Kaydı: İMO-2009-3318
Rapor Sayfa Sayısı: 4
Ekler: Fotoğraf albümü ve kroki
Sabit İrtibat: 0312 418 77 66
"""

    savunma_layihasi = f"""# ANKARA 7. ASLİYE HUKUK MAHKEMESİNE
## DAVALI SAVUNMA LAYİHASI

**MAHKEME:** Ankara 7. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/12345
**TARİH:** 25.03.2025

**DAVALI:** Ahmet Yılmaz İnşaat Ltd. Şti.
**ADRES:** Mehmet Akif Ersoy Caddesi No: 100 Yenimahalle/Ankara
**VEKİLİ:** Av. Sinan Yıldız

**DAVACI:** Ömer Faruk Akın
**VEKİLİ:** Av. Cemalettin Aydın

## SAVUNMALARIMIZ
1. Müvekkil Ahmet Yılmaz İnşaat Ltd. Şti. tüm imalatları Mustafa Kemal Mahallesi
   projesi kapsamında fen ve sanat kurallarına uygun gerçekleştirmiştir.
2. Davacı tanığı Leyla Çınar (TCKN: {tc_tanik}) şirket çalışanı olmayıp olay yeri
   olan İstiklal Caddesi ile Sakarya Sokak kesişimi mevkiinde bulunmamıştır.
3. Evrak Barkod No: {barkod1} ile sunulan fotoğraf kayıtları da gerçeği yansıtmaz;
   PTT Barkod: {barkod2} üzerinden tebligat süresinde yapılmıştır.
4. Savaş mağduriyeti olmaksızın mücbir sebep sayılabilecek aşırı yağış nedeniyle
   oluşan zarardan şirket sorumlu tutulamaz; 125.400,00 TL talebi reddedilmelidir.
5. Atatürk Anadolu Lisesi ile Dr. Sami Ulus Çocuk Hastanesi çevresindeki belediye
   altyapı hatları belediye sorumluluğundadır.

## SONUÇ VE İSTEM
Davanın reddine karar verilmesini davalı vekili olarak arz ederim.

## EKLER
1. Belediye altyapı arıza tutanakları,
2. Meteoroloji Genel Müdürlüğü yağış verileri,
3. Şantiye iş güvenliği günlük defter suretleri,
4. Vekâletname örneği ve baro pulu.

## USUL TALEPLERİ
Keşif ve yeniden bilirkişi incelemesi yapılması hususunu saygıyla talep ederiz.

Davalı Vekili
Av. Sinan Yıldız
"""

    karar_metni = f"""# T.C. ANKARA 7. ASLİYE HUKUK MAHKEMESİ
## GEREKÇELİ KARAR

**MAHKEME:** Ankara 7. Asliye Hukuk Mahkemesi
**ESAS NO:** 2025/12345
**KARAR NO:** 2025/67890
**HAKİM:** Hâkim Nuran Yıldırım
**KATİP:** Zabıt Kâtibi Ömer Çetin
**TARİH:** 15.05.2025

**DAVACI:** Ömer Faruk Akın (TCKN: {tc_davaci})
**ADRES:** Zambak Sokak No: 4/2 Çankaya/Ankara
**VEKİLİ:** Av. Cemalettin Aydın

**DAVALI:** Ahmet Yılmaz İnşaat Ltd. Şti.
**VEKİLİ:** Av. Sinan Yıldız

## GEREKÇE VE DELİL DEĞERLENDİRMESİ
Dosyadaki deliller, tanık Leyla Çınar beyanı, bilirkişi raporu, Evrak Barkod No:
{barkod1} ve PTT Barkod: {barkod2} numaralı evraklar birlikte değerlendirildiğinde;
davalı Ahmet Yılmaz İnşaat Ltd. Şti.'nin İstiklal Caddesi ile Sakarya Sokak
kesişimi mevkiindeki şantiyede gerekli önlemleri almadığı sabit olmuştur.

## HÜKÜM
1. Davanın KABULÜNE,
2. 125.400,00 TL tazminatın davacı Ömer Faruk Akın'a ödenmesine,
3. Vekâlet ücretinin davalıdan tahsiline karar verildi.
4. Peşin harcın mahsubu ile bakiye karar harcının davalıdan tahsiline,
5. Kullanılmayan gider avansının karar kesinleştiğinde yatırana iadesine
   karar verildi.

## KANUN YOLU
İşbu karara karşı tebliğ tarihinden itibaren iki hafta içinde Ankara Bölge
Adliye Mahkemesi nezdinde istinaf kanun yolu açıktır.

Hâkim Nuran Yıldırım
Zabıt Kâtibi Ömer Çetin
Karar Tarihi: 15.05.2025
UYAP Karar No: 2025/67890
Tebliğ Tarihi: 20.05.2025
"""

    return Senaryo(
        ad="14_yaniltici_icerik",
        baslik="Yanıltıcı İçerik (False-Positive Tuzakları)",
        dosyalar={
            "01_Dava_Dilekcesi.md": dava_dilekcesi,
            "02_Sirket_ve_Olay_Raporu.md": olay_raporu,
            "03_Savunma_Layihasi.md": savunma_layihasi,
            "04_Karar_Metni.md": karar_metni,
        },
        gizli=[
            tc_davaci, tc_tanik,
            "0532 999 00 11",
            "Zambak Sokak No: 4/2",
            "Ömer Faruk Akın", "Leyla Çınar",
            "Nuran Yıldırım", "Ömer Çetin",
        ],
        korunan=[
            "Mehmet Akif Ersoy Caddesi",
            "Ahmet Yılmaz İnşaat Ltd. Şti.",
            "Dr. Sami Ulus Çocuk Hastanesi",
            "Atatürk Anadolu Lisesi",
            "Mustafa Kemal Mahallesi",
            "deniz kıyısında güneş batarken",
            "kaya ve demir malzemeler",
            "barış ve özgür çalışma ortamı",
            "savaş mağduriyeti olmaksızın",
            barkod1,
            barkod2,
            "2025/12345",
            "2025/67890",
            "125.400,00 TL",
            "İstiklal Caddesi ile Sakarya Sokak kesişimi",
            "Av. Cemalettin Aydın",
            "Av. Sinan Yıldız",
        ],
        kisiler={
            "Ömer Faruk Akın": "DAVACI",
            "Leyla Çınar": "TANIK",
            "Nuran Yıldırım": "HAKİM",
            "Ömer Çetin": "KÂTİP",
        },
        ayni_etiket=[
            [tc_davaci],
            ["Ömer Faruk Akın"],
            ["Leyla Çınar"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 15: Karma Ceza ve Hukuk (Düzeltme Komşu Varyantları)
# ---------------------------------------------------------------------------
def _build_senaryo_15() -> Senaryo:
    tc_katilan = _make_tckn("192837461")
    tc_supheli = _make_tckn("283746592")
    tc_merhum = _make_tckn("374659283")
    tc_magdur = _make_tckn("465928374")
    iban_katilan = _make_iban("00062", "0019283746501928")

    dizin_ve_fezleke = f"""# İZMİR CUMHURİYET BAŞSAVCILIĞI FEZLEKESİ VE DOSYA DİZİNİ

**SORUŞTURMA NO:** 2025/8841
**TARİH:** 18.02.2025
**SUÇ:** Nitelikli Dolandırıcılık ve Güveni Kötüye Kullanma (TCK m. 158, 155)

## TARAFLAR VE BAĞLANTILAR
- **MÜŞTEKİ / KATILAN:** Selin Yıldız (TCKN: {tc_katilan})
- **ŞÜPHELİ/SANIK :** Berkay Alp Sarı (TCKN: {tc_supheli})
- **MAĞDUR (KÜÇÜK):** Küçük Arda Efe Sarı (TCKN: {tc_magdur})
- **ŞİKAYETÇİ VEKİLİ:** Av. Tarık Gürsoy
- **ŞÜPHELİ MÜDAFİİ:** Av. Beste Karaca

İlgili alt belgeler için yerel bağlantılar:
1. [Şikayet Dilekçesi](Katilan_Selin_Yildiz_Sikayet_Dilekcesi.md)
2. [Şüpheli İfadesi](Supheli-Berkay-Sari/Berkay-Alp-Sari.Ifade.md)
3. [Mağdur ve Miras Tutanağı](03_Magdur_ve_Miras_Tutanagi.txt)

## OLAY ÖZETİ VE MALİ TESPİTLER
1. Müşteki Selin Yıldız tarafından savcılığa sunulan dilekçede, şüpheli Berkay Alp Sarı
   ile ortak yürütülen sevkiyat işinde malzeme faturalarının sahte düzenlendiği
   ve tahsil edilen paranın mağdur edilen Yıldız Marmara
   İhracat Pazarlama Ltd. Şti. ticari hesabından çekildiği ileri sürülmüştür.
2. Müşteki Selin Yıldız'ın kullandığı {iban_katilan} IBAN numaralı vadesiz hesaptan
   (Hesap No: 88341209) tarihinde yapılan aktarım tutarı 24.500,00 TL olup
   karşı dekontta (Hesap No: 88341209; şube kodu 104) şeklinde kayıtlıdır.
3. Muhasebe incelemesinde referans gösterilen Hesap No: 24.500,00 TL tutarındaki
   fatura bedeli ile 2025/419 esas sayılı dosya borcu ayrıca ayrıştırılmıştır.
4. Soruşturma evrakında Müteveffa Kerim Yılmaz (TCKN: {tc_merhum}) adına düzenlenen
   eski tarihli vekâletnamede SARI Berkay Alp ibaresi görülmüştür.
5. Şüpheli hakkındaki yakalama emri Atatürk Bulvarı üzerindeki İzmir Bölge Adliye
   Komutanlığı nöbetçi birimine de bilgi olarak gönderilmiştir.
6. Dosya kapsamında Yıldız Marmara İhracat Pazarlama Ltd. Şti. yetkilisi beyanı
   ayrıca ticaret sicil gazetesinden teyit edilmiştir.
7. Savcılık kâtibi tarafından dijital makbuz hash kayıtları arşive işlenmiştir.
8. Ön inceleme raporu Cumhuriyet Savcısı Orhan Demirci tarafından onaylanmıştır.
9. Kolluk tutanakları ek klasöre dizi pusulası ile bağlanmıştır.
10. Mali şube uzman mütalaası CD ekinde fiziki dosyaya konmuştur.
11. Şüpheli banka dekontlarındaki işlem saatleri kamera kayıtlarıyla eşleştirilmiştir.
12. Sevkiyat irsaliyelerinin asılları ticaret sicil memurluğundan celp edilmiştir.
13. Tanık dinleme oturumunun gelecek celsede yapılmasına karar verilmiştir.
14. UYAP evrak doğrulama kodu sorgulanarak dosyaya işlenmiştir.
15. Fezleke suretleri ilgili taraflara elektronik tebligatla gönderilmiştir.
"""

    sikayet_dilekcesi = f"""# İZMİR CUMHURİYET BAŞSAVCILIĞINA

**DOSYA NO:** 2025/8841 Sor.
**MÜŞTEKİ (KATILAN):** Selin Yıldız (TCKN: {tc_katilan})
**ADRES:** Lale Sokak No: 12/4 Bornova/İzmir
**CEP TEL:** 0533 444 55 66
**VEKİLİ:** Av. Tarık Gürsoy

**ŞÜPHELİ:** Berkay Alp Sarı (TCKN: {tc_supheli})

## AÇIKLAMALAR
1. Müşteki Selin Yıldız ile şüpheli Berkay Alp Sarı arasında imzalanan adi yazılı
   protokol gereğince sevkiyat bedelleri tahsil edilmek üzere teslim alınmıştır.
2. Müvekkile Selin Yıldız (TCKN: {tc_katilan}) adına açılan bankadaki 88341209 hesap
   numarasına yatırılması gereken tutarlar şüphelinin yönlendirdiği farklı kanallara
   aktarılmıştır.
3. Ayrıca Merhum Kerim Yılmaz (TCKN: {tc_merhum}) ile bağlantılı eski hisse devir
   sözleşmesinde Küçük Arda Efe Sarı (TCKN: {tc_magdur}) lehine kayıt bulunduğu,
   ancak eski tapu ve banka dekontlarında SARI Arda Efe şeklinde geçtiği saptanmıştır.
4. Karşı taraf Yıldız Marmara İhracat Pazarlama Ltd. Şti. unvanlı firmanın bu
   işlemlerde yalnızca taşeron faturası düzenlediği görülmüştür.
5. Şüphelinin cep telefonu olan 0532 777 88 99 numarasından gönderdiği mesajlar
   ekran görüntüsü olarak dilekçe ekine sunulmuştur.
6. Bu kapsamda Şüpheli Tarafından yapılan savunmaların hukuki dayanağı yoktur.
7. Yine Şüpheli Banka şubesinden temin edilen ekstrelerde 88341209 hesabı açıkça
   görülmektedir.
8. Müşteki Olarak beyanlarımızın tespiti ile şüphelilerin cezalandırılması gerekir.
9. Soruşturma makamına sunulan bilirkişi ön raporu 2025/419 esas sayılı dosya ile
   birleştirilmek üzere incelenmiştir.
10. Tanık olarak kimliği tespit edilen başka bir şahıs bulunmamaktadır.
11. Delillerin karartılma tehlikesi nedeniyle iletişimin tespiti talep olunur.
12. Gereğinin yapılmasını vekaleten arz ve talep ederiz.
13. Ek: Dekont suretleri ve mesaj dökümü.
14. İnceleme için bkz: [Fezleke](01_Dizin_ve_Fezleke.md).
15. Tarih: 10.02.2025 - Müşteki Vekili Av. Tarık Gürsoy.
16. İmza: Av. Tarık Gürsoy (Elektronik İmzalıdır).
17. Adres teyidi: Lale Sokak No: 12/4 Bornova/İzmir.
18. Banka hesap bilgileri dilekçe ekinde sunulmuştur.
19. İşbu dilekçe üç nüsha halinde ibraz olunmuştur.
20. Taraf vekillerinin yetki belgeleri vekaletname ile sunulmuştur.
21. Soruşturma evrakının gizliliği gözetilerek kayıt altına alınmıştır.
"""

    ifade_tutanagi = f"""# ŞÜPHELİ İFADE TUTANAĞI

**SORUŞTURMA NO:** 2025/8841
**TARİH:** 15.02.2025
**İFADE VEREN (ŞÜPHELİ):** SARI Berkay Alp (TCKN: {tc_supheli})
**İKAMET ADRESİ:** Gündoğdu Mahallesi Papatya Caddesi No: 30/7 Buca/İzmir
**MÜDAFİİ:** Av. Beste Karaca

## BEYAN
1. Ben SARI Berkay Alp olarak üzerime atılı dolandırıcılık suçlamasını kabul
   etmiyorum. Müşteki Selin Yıldız ile ticari alacak-verecek anlaşmazlığı mevcuttur.
2. Bahsi geçen 88341209 hesap numarası ticari mutabakat amacıyla dekonta yazılmıştır.
3. Ödemenin bir kısmı Yıldız Marmara
   İhracat Pazarlama Ltd. Şti. cari hesabına mahsup edilmiştir.
4. Müteveffa Kerim Yılmaz sağlığında tüm borçların tasfiyesi konusunda mutabıktı.
5. Mağdur Arda Efe Sarı reşit olmadığından işlemler yasal temsilcisi tarafından
   yürütülmüştür; SARI Arda Efe (yani Arda Efe Sarı) herhangi bir zarara uğramamıştır.
6. Yukarıda verdiğim telefon numaram olan 0532 777 88 99 bana aittir.
7. Suçsuz olduğum anlaşılacağından kovuşturmaya yer olmadığına karar verilmesini
   talep ederim.
8. İfade sahibi beyanını okuyarak doğrulamış ve imza altına almıştır.
9. Zabıt kâtibi huzurunda düzenlenen işbu tutanak tarafımızca imzalandı.
10. İfade saati: 14:20 — Bitiş: 15:05.
11. Soruşturma memuru: Komiser Kemal Aktaş (Sicil: 334455).
12. Müdafii hazır bulunmuştur: Av. Beste Karaca.
13. Şüpheliye CMK 147. madde hakları eksiksiz hatırlatılmıştır.
14. Ek beyan: Müşteki {iban_katilan} numaralı hesabına iade planı sunuldu.
15. Tutanağın bir sureti müdafie teslim edildi.
16. Kayıt altına alınan elektronik imza doğrulandı.
17. İfade alma işlemi baskı olmaksızın tamamlandı.
18. Başka ekleyeceğim bir husus yoktur.
19. Bağlı dilekçe: [Şikayet](Katilan_Selin_Yildiz_Sikayet_Dilekcesi.md).
20. Evrak UYAP sistemine taranarak aktarılmıştır.
21. Tutanak iki sayfa olarak kaleme alınmıştır.
22. Tarafların kimlik bilgileri MERNİS üzerinden teyit edildi.
23. İfade odası ses ve görüntü kaydı arşive konmuştur.
24. İşlem güvenliği protokolü tamamlanmıştır.
25. Dosya numarası 2025/8841 olarak kayda geçmiştir.
26. Şüphelinin okuma yazma bildiği beyanı ile tutanak altına alınmıştır.
27. İfade tutanağı saati ve tarihi elektronik imza ile sabitlenmiştir.
28. Cumhuriyet savcısının talimatı doğrultusunda ek araştırma yapılmayacaktır.
"""

    miras_tutanagi = f"""NÖBETÇİ SULH CEZA HAKİMLİĞİNE SUNULAN EK TUTANAK
DOSYA: 2025/8841
TARİH: 17.02.2025

A. KİMLİK BİLGİLERİ VE YAKINLIK KAYITLARI
1. Müteveffa Kerim Yılmaz (TCKN: {tc_merhum}) - Doğum: 01.05.1955
2. Küçük Arda Efe Sarı (TCKN: {tc_magdur}) - Velisi aracılığıyla mağdur
3. Müşteki Selin Yıldız (TCKN: {tc_katilan})
4. Şüpheli Berkay Alp Sarı (TCKN: {tc_supheli})

B. BANKA VE ŞİRKET TESPİTLERİ
- Banka incelemesinde 88341209 numaralı hesap üzerinden yapılan transfer doğrulandı.
- Fatura kesen Yıldız Marmara İhracat Pazarlama Ltd. Şti. aktif mükellef görünüyor.
- Adres araştırmasında Papatya Caddesi ile Lale Sokak kayıtları ayrı tutuldu.
- Tutanakta geçen 24.500,00 TL tutar ile 2025/419 esas numarası korunmalıdır.
- Müşteki Selin Yıldız tarafından sunulan ek dekontlar klasöre eklenmiştir.
- Şüpheli Berkay Alp Sarı hakkında adli kontrol değerlendirmesi yapılmıştır.
- Merhum Kerim Yılmaz ile Berkay Alp Sarı arasındaki eski protokol örneği eklendi.
- Bu tutanak dört nüsha olarak düzenlenmiş ve dosya dizinine kaydedilmiştir.
- Dizi referansı: ilgili şikayet dilekçesi ve şüpheli ifade tutanağıdır.
- Mahkeme veya savcılık talep ettiğinde ek bilirkişi incelemesi yapılacaktır.
- Elektronik evrak doğrulama kodu geçerlidir.
- Tutanak altındaki imzalar taraflarca okunarak atılmıştır.
- İşlem saati 16:40 itibarıyla sonlandırılmıştır.
- Sonuç olarak tüm deliller soruşturma savcısına sunulmuştur.
- İlgili savcılık: Cumhuriyet Savcısı Orhan Demirci.
- İlgili vekil: Av. Tarık Gürsoy.
- İlgili müdafi: Av. Beste Karaca.
- Tutanağın kapsamı olay yeri kayıtları ile örtüşmektedir.
- Ek belge bulunmadığından oturum kapatılmıştır.
- Evrak numarası UYAP dizi pusulasında 4. sırada yer alır.
- Soruşturma dosyasındaki tüm faturalar mali şubede incelenmiştir.
- İlgili ticaret sicil kaydı İzmir Ticaret Odası arşivinden getirtilmiştir.
- Mağdur çocuğun yasal temsilcisi ayrıca bilgilendirilmiştir.
- Gizlilik kararı bulunmayan ek belgeler taraflara açılmıştır.
- İşbu ek tutanak nöbetçi hakimlik kalemine teslim edilmiştir.
- Kayıt numarası: 2025/8841-EK-04.
- Tüm sayfalar paraflanarak taramaya hazır hale getirilmiştir.
- Saygıyla arz olunur.
- Evrak tarama işlemi yazı işleri kalemi tarafından tamamlanmıştır.
- Ek dosya listesi dijital ortamda muhafaza edilmektedir.
"""

    return Senaryo(
        ad="15_karma_ceza_hukuk",
        baslik="Karma Ceza-Hukuk (Düzeltme Komşu Varyantları)",
        dosyalar={
            "01_Dizin_ve_Fezleke.md": dizin_ve_fezleke,
            "Katilan_Selin_Yildiz_Sikayet_Dilekcesi.md": sikayet_dilekcesi,
            "Supheli-Berkay-Sari/Berkay-Alp-Sari.Ifade.md": ifade_tutanagi,
            "03_Magdur_ve_Miras_Tutanagi.txt": miras_tutanagi,
        },
        gizli=[
            tc_katilan, tc_supheli, tc_merhum, tc_magdur,
            iban_katilan,
            "88341209",
            "0533 444 55 66", "0532 777 88 99",
            "Lale Sokak No: 12/4",
            "Papatya Caddesi No: 30/7",
            "Selin Yıldız", "Selin_Yildiz",
            "Berkay Alp Sarı", "Berkay-Alp-Sari", "Berkay-Sari", "SARI Berkay Alp",
            "Kerim Yılmaz",
            "Arda Efe Sarı",
            "Orhan Demirci",
        ],
        korunan=[
            "Yıldız Marmara İhracat Pazarlama Ltd. Şti.",
            "24.500,00 TL",
            "2025/419",
            "2025/8841",
            "Av. Tarık Gürsoy",
            "Av. Beste Karaca",
            "Atatürk Bulvarı",
        ],
        kisiler={
            "Selin Yıldız": "MÜŞTEKİ",
            "Berkay Alp Sarı": "ŞÜPHELİ",
            "Kerim Yılmaz": "KİŞİ",
            "Arda Efe Sarı": "MAĞDUR",
            "Orhan Demirci": "SAVCI",
        },
        ayni_etiket=[
            ["88341209"],
            ["Selin Yıldız"],
            ["Berkay Alp Sarı", "SARI Berkay Alp"],
            ["Kerim Yılmaz"],
            ["Arda Efe Sarı"],
        ],
    )


# ---------------------------------------------------------------------------
# Senaryo 16: Çok Belgeli İcra ve İş Hukuku Bağlantılı Takip (Komşu Varyantlar)
# ---------------------------------------------------------------------------
def _build_senaryo_16() -> Senaryo:
    tc_alacakli = _make_tckn("152637481")
    tc_borclu = _make_tckn("263748592")
    tc_isveren_vek = _make_tckn("374859603")
    tc_ucuncu = _make_tckn("485960714")
    iban_alacakli = _make_iban("00015", "0055667788990011")

    odeme_emri = f"""# ANKARA 12. İCRA MÜDÜRLÜĞÜ ÖRNEK NO: 7 ÖDEME EMRİ

**ESAS NO:** 2025/1042
**TARİH:** 04.03.2025

**ALACAKLI / DAVACI:** Nihal Kaya (TCKN: {tc_alacakli})
**ALACAKLI ADRESİ:** Sedef Sokak No: 9/3 Çankaya/Ankara
**VEKİLİ:** Av. Serdar Polat

**BORÇLU (DAVALI):** Haluk Mert Demir (TCKN: {tc_borclu})
**BORÇLU ADRESİ:** Menekşe Caddesi No: 22/8 Yenimahalle/Ankara

**TOPLAM ALACAK:** 78.250,00 TL (Hesap No: 45.800,50 ve 2025/1042 takip bakiyesi hariç)

## TAKİP DAYANAĞI VE BELGELER
1. İlgili ek belgeler:
   - [Mal Beyanı](Borclu_Haluk_Mert_Demir_Mal_Beyani.md)
   - [İhtarname](<Alacakli.Nihal.Kaya/Nihal.Kaya-Ihtarname.md>)
2. Alacaklı Nihal Kaya tarafından kiracı Haluk Mert Demir aleyhine başlatılan
   takibin ödeme kalemleri arasında Trakya Güneş
   Gıda Pazarlama Ltd. Şti. tarafından kesilen faturalar da bulunmaktadır.
3. Tahsilatlar için bildirilen banka hesapları: Müşteri No: 61904823. Bu hesap
   dışında dekontta yer alan (Hesap Numarası: 55019284; şube 0412) üzerinden de
   kısmi ödeme yapıldığı görülmüştür.
4. İşveren vekili Selçuk Aksoy (TCKN: {tc_isveren_vek}) tarafından imzalanan
   teslim tutanağı takip dayanağı olarak dosyaya konmuştur.
5. Aynı taşınmazda Merhume Ayhan Toprak (TCKN: {tc_ucuncu}) adına kayıtlı
   eski elektrik aboneliği devir tutanağı dosyada mevcuttur.
6. İşbu ödeme emri 7 gün içinde itiraz edilmediği takdirde kesinleşecektir.
7. Ödemelerin {iban_alacakli} numaralı IBAN hesabına yapılması ihtar olunur.
8. Tebligat memuru imzalı mazbata takip dosyasına bağlanmıştır.
9. Alacaklı vekili Av. Serdar Polat harç ve masraf makbuzlarını ibraz etmiştir.
10. Borçlu telefon numarası 0542 333 22 11 olarak kayda alınmıştır.
11. İcra müdürlüğü veznesine yatırılan teminat bedeli ayrıca işlenmiştir.
12. Dosya kapağında yer alan 2025/1042 esas numarası bütün eklerde aynıdır.
13. Takip talebinde faiz oranı yıllık yüzde 24 olarak belirtilmiştir.
14. Menekşe Caddesi ve Sedef Sokak üzerindeki tebligat adresleri ayrıdır.
15. İtiraz süresi dolduğunda haciz işlemlerine geçileceği ihtar edildi.
16. İcra harç ve gider avansına ilişkin makbuz suretleri dosyaya eklenmiştir.
17. Ödeme emrine karşı 7 gün içinde itiraz edilebileceği ayrıca belirtilmiştir.
18. Tebliğ tarihi UYAP evrak kayıt sistemi üzerinden takip edilmektedir.
19. İşbu örnek icra müdürlüğü mührü ile onaylanmıştır.
"""

    mal_beyani = f"""# MAL BEYANI DİLEKÇESİ

**ANKARA 12. İCRA MÜDÜRLÜĞÜNE**
**DOSYA NO:** 2025/1042
**BORÇLU (DAVALI):** Haluk Mert Demir (TCKN: {tc_borclu})
**CEP TEL:** 0542 333 22 11

## BEYANLAR
1. Borçlu Haluk Mert Demir tarafından sunulan işbu mal beyanında, gelir kaynağımın
   Trakya Güneş Gıda Pazarlama Ltd. Şti. nezdindeki danışmanlık ödemeleri olduğu
   bildirilmektedir.
2. Ayrıca DEMİR Haluk Mert adına bankada bulunan 61904823 hesap ile 55019284
   numaralı hesaplar dışında başkaca aktif mevduat hesabım bulunmamaktadır.
3. Geçmiş dönemde Kiraya Veren Nihal Kaya ile yapılan kira kontratında ödenen
   tutarlar 78.250,00 TL sınırını aşmamaktadır.
4. Dosyadaki teslim tutanağında imzası bulunan Selçuk Aksoy (TCKN: {tc_isveren_vek})
   yalnızca depo teslim görevlisidir; taraf sıfatı işveren temsilciliğinden ibarettir.
5. Merhume Ayhan Toprak adına kayıtlı eski abonelik kapatılmıştır.
6. Alacaklı Nihal Kaya vekili Av. Serdar Polat ile haricen ödeme planı görüşülmüştür.
7. Borçlu Tarafından sunulan bu beyan İİK m. 74 gereğince süresindedir.
8. Haluk Mert Demir adına başka taşınır veya taşınmaz malvarlığı kaydı yoktur.
9. Gereğinin yapılmasını saygıyla arz ederim.
10. Borçlu İmza: Haluk Mert Demir
11. Tarih: 10.03.2025
12. Ek: Banka hesap dökümü ve kira makbuzları.
13. Not: İlgili belge [İhtarname](<Alacakli.Nihal.Kaya/Nihal.Kaya-Ihtarname.md>).
14. Müvekkil değil asil olarak beyanda bulunulmuştur.
15. Masraf tutarı vezneye depo edilmiştir.
16. İşbu dilekçe iki sayfa halinde sunulmuştur.
17. Adres değişikliği olursa ayrıca bildirilecektir.
18. SGK hizmet dökümü dilekçe ekinde sunulmuştur.
19. Taşınmaz tapu sorgusunun olumsuz geldiği tespit edilmiştir.
20. Araç tescil kaydı bulunmadığına dair yazı eklenmiştir.
21. Aylık gider listesi ile kira makbuzları dosyaya konulmuştur.
22. Beyanın doğruluğu tarafımca taahhüt edilmektedir.
23. Tebligatların aynı ikamet adresine yapılması talep olunur.
24. UYAP üzerinden fiziki imza taratılarak gönderilmiştir.
25. İkinci bir ödeme planı önerisi ilerleyen günlerde sunulabilecektir.
26. Duruşma veya ek açıklama istenmesi halinde katılım sağlanacaktır.
27. Saygılarımla icra müdürlüğüne arz ederim.
28. Evrak ekleri numaralandırılarak dizi pusulasına işlenmiştir.
"""

    ihtarname = f"""# NOTER İHTARNAMESİ

**KEŞİDECİ / ALACAKLI:** Nihal Kaya (TCKN: {tc_alacakli})
**VEKİLİ:** Av. Serdar Polat
**MUHATAP (BORÇLU):** Haluk Mert Demir (TCKN: {tc_borclu})

## İHTAR KONUSU
1. Kiraya Veren Nihal Kaya ile Kiracı Haluk Mert Demir arasında akdedilen sözleşme
   uyarınca ödenmesi gereken 78.250,00 TL bakiye borcun 61904823 ve 55019284
   numaralı hesaplarla ilişkili ödemeleri yapılmamıştır.
2. Teslim tutanağının tanzim edildiği tarihte İşveren vekili Selçuk Aksoy tarafından
   malzeme teslimi teyit edilmiş, Trakya Güneş Gıda Pazarlama Ltd. Şti. sevkiyat
   fişleri ibraz olunmuştur.
3. Ödemelerin {iban_alacakli} hesabına yapılmaması üzerine Ankara 12. İcra
   Müdürlüğü 2025/1042 sayılı takip dosyası açılmıştır.
4. Eski kiracı Merhume Ayhan Toprak döneminden kalan aidat borcu ayrı hesaplanmıştır.
5. Sayın muhatap DEMİR Haluk Mert işbu ihtarnamenin tebliğinden itibaren üç gün
   içinde ödeme yapmazsa haciz süreci başlatılacaktır.
6. İhtarnamenin bir sureti Noterlik dairesinde saklanacaktır.
7. İşbu ihtarname Beyoğlu 5. Noterliği kanalıyla keşide edilmiştir.
8. Alacaklı Vekili Av. Serdar Polat imzalıdır.
9. Muhatap adresi: Menekşe Caddesi No: 22/8 Yenimahalle/Ankara.
10. Keşideci adresi: Sedef Sokak No: 9/3 Çankaya/Ankara.
11. İhtar masrafları takip talebine dahil edilecektir.
12. İlgili evrak: [Mal Beyanı](Borclu_Haluk_Mert_Demir_Mal_Beyani.md).
13. Takip rakamları Hesap No: 45.800,50 kalemiyle karıştırılmamalıdır.
14. Süresinde cevap verilmediği takdirde yasal yollara başvurulacaktır.
15. Tarih: 20.02.2025 - Ankara.
16. Noterlik makbuzu ve posta barkod numarası ihtarname arkasına işlenmiştir.
17. Sayın noter işbu ihtarnamenin üç nüsha olarak düzenlenmesini arz ederim.
18. Tebliğ şerhi kesinleştikten sonra takip dosyasına ibraz edilecektir.
19. Keşideci vekili iletişim bilgileri vekaletnamede yer almaktadır.
20. İhtarname içeriğindeki süre tebliğ gününü izleyen günden itibaren başlar.
21. Kısmi ödeme yapılması halinde bakiye tutar üzerinden faiz işlemeye devam eder.
22. Tüm fazlaya ilişkin talep ve dava hakları saklı tutulmuştur.
23. Noter başkatibi tarafından evrak kaydı tamamlanmıştır.
24. Posta dağıtım raporu elektronik ortamda takip edilecektir.
25. İlgili evrak sureti arşiv dosyasında muhafaza olunmaktadır.
26. İşbu ihtarname vekaletnameye istinaden düzenlenmiştir.
27. Muhatap tarafından cevap verilmesi halinde dosyaya eklenecektir.
28. Keşideci vekili imzası ile onaylanmıştır.
"""

    haciz_muzekkeresi = f"""ANKARA 12. İCRA MÜDÜRLÜĞÜ BANKA HACİZ MÜZEKKERESİ
ESAS NO: 2025/1042
TARİH: 18.03.2025

1. Borçlu DEMİR Haluk Mert (TCKN: {tc_borclu}) adına bankanız nezdinde bulunan
   mevduatların ve özellikle 61904823 ile 55019284 numaralı hesap bakiyelerinin
   78.250,00 TL alacak miktarınca haczine karar verilmiştir.
2. Alacaklı Nihal Kaya (TCKN: {tc_alacakli}) vekili Av. Serdar Polat'ın talebi
   kabul edilerek müzekkere tanzim olunmuştur.
3. Tapu ve MERNİS kayıtlarında DEMİR Haluk Mert ile Haluk Mert Demir kaydının
   aynı şahıs olduğu teyit edilmiştir.
4. Dosyada adı geçen Ayhan Toprak ve Selçuk Aksoy yönünden haciz uygulanmaz.
5. Üçüncü kişi Trakya Güneş Gıda Pazarlama Ltd. Şti. nezdindeki hak ve alacaklara
   ilişkin 89/1 ihbarnamesi ayrıca gönderilmiştir.
6. İcra müdürlüğü kâtibi tarafından UYAP üzerinden elektronik olarak iletilmiştir.
7. Bankanın 7 iş günü içinde yazılı cevap vermesi rica olunur.
8. Cevabi yazıda dosya esas numarası 2025/1042 mutlaka belirtilmelidir.
9. Vekalet ücreti ve faiz dökümü ödeme tarihinde ayrıca güncellenecektir.
10. Fazla tahsilat halinde iade yapılacaktır.
11. İcra Müdür Yardımcısı: Mustafa Şahin (Sicil: 112244).
12. Bu yazı İİK m. 89 gereğince düzenlenmiştir.
13. Tahsilat bildirimi alacaklı hesabına {iban_alacakli} aktarılacaktır.
14. Müzekkere eki evraklar elektronik imza ile mühürlüdür.
15. Banka genel müdürlüğü kayıtları esas alınacaktır.
16. Kayıt doğrulama numarası sistem tarafından üretilmiştir.
17. Posta veya KEP ile tebliğ edilen nüsha dosyada muhafaza edilir.
18. Gereği bilgilerinize rica olunur.
19. Bloke edilen tutarlar icra dairesinin banka hesabına aktarılacaktır.
20. Yanlış hesaba yapılan aktarımlar ivedilikle iade edilecektir.
21. Yasal kesintiler ve EFT masrafları ilgili mevzuata göre hesaplanır.
22. Cevap verilmemesi halinde İİK m. 357 uyarınca işlem yapılacağı ihtar olunur.
23. Şube müdürlüklerine iç yazışma ile ayrıca bildirim yapılması bankanın yetkisindedir.
24. Müşterek hesap varsa hisse oranının bildirilmesi gerekmektedir.
25. Mevduat rehni veya önceki haciz şerhleri sıra cetveliyle bildirilmelidir.
26. Döviz tevdiat hesapları işlem tarihindeki kur üzerinden raporlanacaktır.
27. Elektronik ortamda gelen yanıtlar doğrudan dosya evrakına işlenecektir.
28. Ekli takip talebi örneği bilgi için gönderilmiştir.
29. İcra dairesi banka hesap bilgileri sistemde kayıtlıdır.
30. İkinci bir müzekkere yazılmasına gerek kalmaksızın netice bildirilecektir.
31. Evrak numarası dosya dizininde yer almaktadır.
32. Gereği için bankanız genel müdürlüğüne tevdi olunur.
"""

    return Senaryo(
        ad="16_cok_belgeli_icra",
        baslik="Çok Belgeli İcra Takibi (Komşu Varyantlar)",
        dosyalar={
            "01_Odeme_Emri.md": odeme_emri,
            "Borclu_Haluk_Mert_Demir_Mal_Beyani.md": mal_beyani,
            "Alacakli.Nihal.Kaya/Nihal.Kaya-Ihtarname.md": ihtarname,
            "03_Banka_Haciz_Muzekkeresi.txt": haciz_muzekkeresi,
        },
        gizli=[
            tc_alacakli, tc_borclu, tc_isveren_vek, tc_ucuncu,
            iban_alacakli,
            "61904823", "55019284",
            "0542 333 22 11",
            "Sedef Sokak No: 9/3",
            "Menekşe Caddesi No: 22/8",
            "Nihal Kaya", "Nihal.Kaya",
            "Haluk Mert Demir", "Haluk_Mert_Demir", "DEMİR Haluk Mert",
            "Selçuk Aksoy",
            "Ayhan Toprak",
        ],
        korunan=[
            "Trakya Güneş Gıda Pazarlama Ltd. Şti.",
            "78.250,00 TL",
            "45.800,50",
            "2025/1042",
            "Av. Serdar Polat",
            "Beyoğlu 5. Noterliği",
        ],
        kisiler={
            "Nihal Kaya": "ALACAKLI",
            "Haluk Mert Demir": "BORÇLU",
            "Selçuk Aksoy": "KİŞİ",
            "Ayhan Toprak": "KİŞİ",
        },
        ayni_etiket=[
            ["61904823"],
            ["55019284"],
            ["Nihal Kaya"],
            ["Haluk Mert Demir", "DEMİR Haluk Mert"],
            ["Selçuk Aksoy"],
            ["Ayhan Toprak"],
        ],
    )


def _build_senaryo_17() -> Senaryo:
    dilekce = """# İSTANBUL ANADOLU 5. ASLİYE HUKUK MAHKEMESİ'NE

**DAVACI** : Ahmet Can Yılmaz (T.C. Kimlik No: 10000000146)
Adres: Caferağa Mah. Moda Cad. No:12 D:3 Kadıköy/İstanbul Tel: 0532 111 22 33
**VEKİLİ** : Av. Ayşe Kaya, İstanbul Barosu Sicil No: 45678
**DAVALILAR** : 1- Mehmet Demir (TCKN: 10000000078)
2- Zeynep Demir
3- Demir İnşaat Ltd. Şti.
4- Türkiye İş Bankası A.Ş.
**KONU** : Alacak Davası

## AÇIKLAMALAR

1. Davacı Ahmet Yılmaz ile davalı Mehmet Demir arasında 12.03.2024 tarihinde sözleşme yapılmıştır. AHMET YILMAZ'ın ödediği 125.000,00 TL iade edilmemiştir.
2. A. Yılmaz olay günü Ahmet Yılmaz Caddesi üzerindeki ofise gitmiş, Mehmet DEMİR'e ihtar çekmiştir. Yılmaz o gün yalnızdı; Ahmet de bunu doğrular.
3. Olayı tanık Fatma Şahin görmüştür. Tanık Fatma Şahin'in beyanı ektedir. Fatma Şahin, Mehmet Demir İnşaat Ltd. Şti. çalışanıdır.
4. Bilirkişi Hasan Öztürk raporunda, Dr. Elif Arslan'ın muayenesine atıf yapmıştır. Hâkim Murat Öz 112233
5. Davalı Zeynep Demir, Mehmet Demir'in eşidir. Baba adı: Hasan, Anne adı: Emine. Davacı Tarafından sunulan Dava Dilekçesi incelendi. Davalı Banka Genel Müdürlüğü cevap verdi. Tanık Olarak dinlenen kişi.
6. Ayrıntı için bkz. [Ahmet Yılmaz dava dilekçesi](Ahmet%20Yılmaz%20dava%20dilekçesi.md)
7. Ali Veli Kaya isimli komşu da oradaydı. Sanık Sıfatıyla ifadesi alınan Kemal Aydın suçlamayı reddetti.
"""

    tutanak = """# DURUŞMA TUTANAĞI
ESAS NO: 2024/623
DAVACI : AHMET CAN YILMAZ
DAVALI : MEHMET DEMİR
TANIK : FATMA ŞAHİN, Ali kızı, 1980 doğumlu
Adı Soyadı : Kemal Aydın
Tanık Fatma Şahin soruldu: "Demir Mehmet parayı aldı" dedi. Yılmaz Ahmet haklıdır.
Davacı Vekili Av. Ayşe Kaya söz aldı. Davalı Mehmet Demir Bey duruşmaya gelmedi.
"""

    manifest = '{"taraflar":[{"ad":"Ahmet Can Yılmaz","sifat":"Davacı"},{"ad":"Demir İnşaat Ltd. Şti.","sifat":"Davalı"}]}'

    return Senaryo(
        ad="17_ad_sirket_cakismasi",
        baslik="Ad-Şirket Çakışması ve 2/3 Belirteç Birleştirme Gerileme Testi",
        dosyalar={
            "Dilekçeler/Ahmet Yılmaz dava dilekçesi.md": dilekce,
            "tutanak.md": tutanak,
            "uyap-project.json": manifest,
        },
        gizli=[
            "10000000146",
            "10000000078",
            "0532 111 22 33",
            "Moda Cad. No:12 D:3",
            "45678",
            "112233",
            "Ahmet Can Yılmaz",
            "Zeynep Demir",
            "Fatma Şahin",
            "Kemal Aydın",
            "A. Yılmaz",
            "Yılmaz Ahmet",
            "Demir Mehmet",
            "Ali Veli Kaya",
            "Murat Öz",
        ],
        korunan=[
            "Demir İnşaat Ltd. Şti.",
            "Mehmet Demir İnşaat Ltd. Şti.",
            "Türkiye İş Bankası A.Ş.",
            "Ahmet Yılmaz Caddesi",
            "Av. Ayşe Kaya",
            "Hasan Öztürk",
            "Dr. Elif Arslan",
            "125.000,00 TL",
            "2024/623",
            "Davacı Tarafından",
            "Davalı Banka Genel Müdürlüğü",
            "Tanık Olarak",
            "Sanık Sıfatıyla",
        ],
        kisiler={
            "Ahmet Can Yılmaz": "DAVACI",
            "Mehmet Demir": "DAVALI",
            "Zeynep Demir": "DAVALI",
            "Fatma Şahin": "TANIK",
            "Ali Veli Kaya": "KİŞİ",
            "Kemal Aydın": "KİŞİ",
            "Murat Öz": "HAKİM",
        },
        ayni_etiket=[
            ["Ahmet Can Yılmaz", "AHMET CAN YILMAZ", "AHMET YILMAZ", "A. Yılmaz", "Yılmaz Ahmet"],
            ["MEHMET DEMİR", "Mehmet DEMİR", "Demir Mehmet"],
            ["Zeynep Demir"],
            ["Fatma Şahin", "FATMA ŞAHİN"],
            ["Ali Veli Kaya"],
            ["Kemal Aydın"],
        ],
    )


def _build_senaryo_18() -> Senaryo:
    dava = """# ANKARA 3. AİLE MAHKEMESİ SAYIN HÂKİMLİĞİ'NE
DAVACI (KARŞI DAVALI) : Selin Nur Aktaş, T.C. 10000000146
Adres: Kızılay Mah. Gazi Mustafa Kemal Bulvarı No:45/7 Çankaya/ANKARA
VEKİLİ : Av. Burak Tuna - Ankara Barosu 23456
DAVALI (KARŞI DAVACI) : Orhan Aktaş (TCKN: 10000000078), Yenimahalle Mah. 12. Sok. No:3 Keçiören/Ankara
KONU : Boşanma, velayet ve nafaka talebidir.

AÇIKLAMALAR
1. Müvekkil Selin Aktaş ile davalı Orhan Aktaş 14.06.2015 tarihinde evlenmiş, müşterek çocuk Defne Aktaş 2018 doğumludur.
2. Davalı, Aktaş Otomotiv Sanayi ve Ticaret Ltd. Şti. ortağıdır; şirket merkezi Ostim OSB 1234. Cad. No:8 Yenimahalle/Ankara adresindedir.
3. AKTAŞ Selin Nur'un annesi Gülten Hanım ve tanık Derya Koç olayları bilmektedir. Derya Koç'un telefonu 0 532 444 55 66'dır.
4. Davalı 05.01.2024 günü Tunalı Hilmi Caddesi üzerindeki kafede müvekkile hakaret etmiştir. Savaş çıkmış gibi bağırmış, Deniz kenarındaki evi satacağını söylemiştir.
5. Orhan Bey aylık 85.000 TL gelir elde etmektedir. Selin Hanım çalışmamaktadır. S. Aktaş'ın hesabı: TR33 0006 1005 1978 6457 8413 26
6. Ek: [Derya Koç beyanı](Ekler/Tanik_Derya_Koc_beyani.md)
DELİLLER: Nüfus kaydı, tanık Derya KOÇ, bilirkişi incelemesi, Ziraat Bankası Kızılay Şubesi kayıtları."""

    tanik = """# TANIK BEYANI
TANIK : Derya Koç
Beyanında: "Orhan Aktaş eşine bağırdı, Selin ağlıyordu. Koç Holding önünde karşılaştık." dedi.
Hâkim 123456 Kâtip 234567"""

    return Senaryo(
        ad="18_aile_yakinlar",
        baslik="Aile Yakınları, Bağlantı Hedefi, Ön Ad + Bey/Hanım, Baro Sicili ve Şirket Merkezi",
        dosyalar={
            "dava.md": dava,
            "Ekler/Tanik_Derya_Koc_beyani.md": tanik,
        },
        gizli=[
            "10000000146",
            "10000000078",
            "0 532 444 55 66",
            "TR33 0006 1005 1978 6457 8413 26",
            "Gazi Mustafa Kemal Bulvarı No:45/7",
            "12. Sok. No:3",
            "Derya",
            "Koc",
            "Defne",
            "23456",
            "123456",
            "234567",
            "Selin Nur Aktaş",
            "Selin Aktaş",
            "Orhan Aktaş",
            "Derya Koç",
            "Defne Aktaş",
            "S. Aktaş",
        ],
        korunan=[
            "Aktaş Otomotiv Sanayi ve Ticaret Ltd. Şti.",
            "Ostim OSB 1234. Cad. No:8 Yenimahalle/Ankara",
            "Koç Holding",
            "Tunalı Hilmi Caddesi üzerindeki kafede",
            "Savaş çıkmış gibi",
            "Deniz kenarındaki",
            "Gülten Hanım",
            "Av. Burak Tuna",
            "Ziraat Bankası Kızılay Şubesi",
            "Selin ağlıyordu",
        ],
        kisiler={
            "Selin Nur Aktaş": "DAVACI",
            "Orhan Aktaş": "DAVALI",
            "Derya Koç": "TANIK",
            "Defne Aktaş": "KİŞİ",
        },
        ayni_etiket=[
            ["Selin Nur Aktaş", "Selin Aktaş", "AKTAŞ Selin Nur", "S. Aktaş", "Selin Hanım"],
            ["Orhan Aktaş", "Orhan Bey"],
            ["Derya Koç", "Derya KOÇ"],
            ["Defne Aktaş"],
        ],
    )


def _build_senaryo_19() -> Senaryo:
    belge1 = """# İSTANBUL 2. ASLİYE HUKUK MAHKEMESİ
ESAS NO: 2025/712
DAVACI : Ahmet Can Yılmaz
TCKN: 10000000146
VEKİLİ : Av. Ayşe Kaya
DAVALI : Mehmet Demir
TCKN: 10000000078
ŞİRKET : Demir Yapı İnşaat Ltd. Şti.

## AÇIKLAMALAR
1. İşbu dosyada Ahmet Can
Yılmaz'ın talebi üzerine ihtarname keşide edilmiştir.
2. Davalı Mehmet
Demir'in ödeme yapmadığı sabittir.
3. Olay yerinde bulunan tanık Fatma
Şahin huzurunda tutanak tutulmuştur.
4. Dosya kapsamında AHMET CAN
YILMAZ tarafından 45.000,00 TL bedel ödenmiştir.
5. İşbu dava MEHMET
DEMİR aleyhine açılmıştır.
6. Görüşme Ahmet Can Yılmaz Caddesi üzerindeki ofiste
yapılmış olup Ahmet
Can Yılmaz'a ihtar tebliğ edilmiştir."""

    belge2 = """# CEVAP DİLEKÇESİ
ESAS NO: 2025/712
DAVALI : Mehmet Demir
DAVACI : Ahmet Can Yılmaz

1. Karşı taraf Ahmet Can
Yılmaz ile müvekkil Demir Yapı İnşaat Ltd. Şti.
arasında ticari ilişki vardır.
2. Taraflardan Mehmet
Demir arasında yapılan sözleşme geçerlidir.
3. Tanık Fatma
Şahin'in beyanları gerçeği yansıtmamaktadır.
4. Dosyadaki YILMAZ
Ahmet Can'ın iddiası mesnetsizdir.
5. Ödeme makbuzu DEMİR
Mehmet tarafından sunulmuştur.
6. Daha sonra Ahmet
Yılmaz'a yapılan bildirim Ahmet Can Yılmaz Caddesi
adresindeki büroda Av. Ayşe Kaya huzurunda okunmuştur."""

    belge3 = """# DURUŞMA TUTANAĞI
ESAS NO: 2025/712
Hâkim Murat Öz 112233
DAVACI : Ahmet Can Yılmaz
DAVALI : Mehmet Demir
TANIK : Fatma Şahin

1. Duruşmada Davacı Ahmet
Can Yılmaz söz aldı ve talebini yineledi.
2. Davalı Mehmet
DEMİR cevap verdi, iddiaları reddetti.
3. Tanık Fatma
ŞAHİN yeminli dinlendi.
4. Beyanında ŞAHİN
Fatma olay gününü ayrıntılarıyla anlattı.
5. Karşı taraf AHMET
CAN YILMAZ'ın talebi hakkında Av. Ayşe Kaya dinlendi.
6. Tutanağın altına Mehmet
Demir'in imzası alındı."""

    return Senaryo(
        ad="19_satir_sonu_bolunmus_adlar",
        baslik="UDF-Benzeri Satır Sonunda Bölünmüş Kişi Adları ve Denetim Doğrulaması",
        dosyalar={
            "01_dava_dilekcesi.md": belge1,
            "02_cevap_dilekcesi.md": belge2,
            "03_durusma_tutanagi.md": belge3,
        },
        gizli=[
            "10000000146",
            "10000000078",
            "112233",
            "Ahmet Can Yılmaz",
            "Mehmet Demir",
            "Fatma Şahin",
            "Murat Öz",
        ],
        korunan=[
            "Demir Yapı İnşaat Ltd. Şti.",
            "Ahmet Can Yılmaz Caddesi",
            "Av. Ayşe Kaya",
            "2025/712",
            "45.000,00 TL",
        ],
        kisiler={
            "Ahmet Can Yılmaz": "DAVACI",
            "Mehmet Demir": "DAVALI",
            "Fatma Şahin": "TANIK",
            "Murat Öz": "HAKİM",
        },
        ayni_etiket=[
            [
                "Ahmet Can Yılmaz",
                "Ahmet Can\nYılmaz",
                "AHMET CAN\nYILMAZ",
                "Ahmet\nCan Yılmaz",
                "YILMAZ\nAhmet Can",
                "Ahmet\nYılmaz",
                "AHMET\nCAN YILMAZ",
            ],
            [
                "Mehmet Demir",
                "Mehmet\nDemir",
                "MEHMET\nDEMİR",
                "DEMİR\nMehmet",
                "Mehmet\nDEMİR",
            ],
            [
                "Fatma Şahin",
                "Fatma\nŞahin",
                "Fatma\nŞAHİN",
                "ŞAHİN\nFatma",
            ],
        ],
    )


SENARYOLAR: List[Senaryo] = [
    _build_senaryo_01(),
    _build_senaryo_02(),
    _build_senaryo_03(),
    _build_senaryo_04(),
    _build_senaryo_05(),
    _build_senaryo_06(),
    _build_senaryo_07(),
    _build_senaryo_08(),
    _build_senaryo_09(),
    _build_senaryo_10(),
    _build_senaryo_11(),
    _build_senaryo_12(),
    _build_senaryo_13(),
    _build_senaryo_14(),
    _build_senaryo_15(),
    _build_senaryo_16(),
    _build_senaryo_17(),
    _build_senaryo_18(),
    _build_senaryo_19(),
]


# ---------------------------------------------------------------------------
# Ortak çalıştırma ve doğrulama yardımcıları
# ---------------------------------------------------------------------------

def _snapshot_tree(folder: str) -> Dict[str, bytes]:
    snap: Dict[str, bytes] = {}
    for root, _dirs, files in os.walk(folder):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, folder).replace("\\", "/")
            with open(fp, "rb") as f:
                snap[rel] = f.read()
    return snap


def _collect_output_texts(dest_folder: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for root, _dirs, files in os.walk(dest_folder):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, dest_folder).replace("\\", "/")
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                out[rel] = f.read()
    return out


def _map_input_to_output_files(
    dosyalar: Dict[str, str],
    out_texts: Dict[str, str],
) -> Dict[str, str]:
    """Girdi göreli yollarını hedef klasördeki maskelenmiş yola eşler."""
    mapping: Dict[str, str] = {}
    used_out = set()
    for in_rel in dosyalar:
        if in_rel in out_texts:
            mapping[in_rel] = in_rel
            used_out.add(in_rel)
            continue
        in_dir, in_base = os.path.split(in_rel)
        in_ext = os.path.splitext(in_base)[1]
        in_tokens = set(re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+", os.path.splitext(in_base)[0]))
        best_rel = None
        best_score = -1
        for out_rel in out_texts:
            if out_rel in used_out or out_rel == UyapRedactor.REPORT_NAME:
                continue
            out_dir, out_base = os.path.split(out_rel)
            if os.path.splitext(out_base)[1] != in_ext:
                continue
            out_tokens = set(re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9]+", os.path.splitext(out_base)[0]))
            score = len(in_tokens & out_tokens) + (2 if in_dir == out_dir else 0)
            if score > best_score:
                best_score = score
                best_rel = out_rel
        if best_rel:
            mapping[in_rel] = best_rel
            used_out.add(best_rel)
    return mapping


def _extract_tags_for_variant(
    senaryo: Senaryo,
    file_map: Dict[str, str],
    out_texts: Dict[str, str],
    variant: str,
) -> Tuple[List[str], List[str]]:
    """
    Bir yazım varyantının girdi belgelerindeki tüm geçtiği yerlerde çıktıda
    hangi etikete dönüştüğünü (veya sızdığını) toplar.
    Dönüş: (bulunan_etiketler, hata_satirlari)
    """
    found_tags: List[str] = []
    errors: List[str] = []
    norm_var = UyapRedactor.normalize_spaces(variant)

    for in_rel, in_raw in senaryo.dosyalar.items():
        if not in_rel.endswith((".md", ".txt")):
            continue
        out_rel = file_map.get(in_rel)
        if not out_rel or out_rel not in out_texts:
            errors.append(f"{in_rel}: çıktı dosyası eşlenemedi")
            continue

        norm_in = UyapRedactor.normalize_spaces(in_raw)
        in_lines = norm_in.splitlines()
        out_lines = out_texts[out_rel].splitlines()

        if "\n" in norm_var:
            out_full = out_texts[out_rel]
            start_pos = 0
            while True:
                pos = norm_in.find(norm_var, start_pos)
                if pos == -1:
                    break
                start_pos = pos + len(norm_var)
                line_start = norm_in.rfind("\n", 0, pos) + 1
                prefix = norm_in[line_start:pos]
                end_pos = pos + len(norm_var)
                next_nl = norm_in.find("\n", end_pos)
                suffix = norm_in[end_pos:(next_nl if next_nl != -1 else len(norm_in))]
                # Satır birleştiği için çıktıda prefix + [ROL_N] + suffix aynı satırda olmalı
                pat_m = re.search(
                    re.escape(prefix) + r"(" + _TAG_RE.pattern + r")" + re.escape(suffix),
                    out_full,
                )
                if not pat_m:
                    errors.append(
                        f"{out_rel}: bölünmüş varyant etikete dönüşmedi ({variant!r})"
                    )
                    continue
                found_tags.append(pat_m.group(1))
        else:
            for idx, line in enumerate(in_lines):
                if norm_var not in line:
                    continue
                check_src_line = line
                for prot in senaryo.korunan:
                    if norm_var in prot and len(prot) > len(norm_var):
                        check_src_line = check_src_line.replace(prot, " ")
                if norm_var not in check_src_line:
                    continue
                target_out_line: Optional[str] = None
                if len(in_lines) == len(out_lines):
                    target_out_line = out_lines[idx]
                else:
                    prefix = line.split(norm_var, 1)[0].strip()
                    anchor = prefix[:20] if prefix else ""
                    if anchor:
                        for ol in out_lines:
                            if anchor in ol:
                                target_out_line = ol
                                break
                    if target_out_line is None and idx < len(out_lines):
                        target_out_line = out_lines[idx]

                if target_out_line is None:
                    errors.append(f"{in_rel}:{idx+1} ({variant!r}) -> karşılık çıktı satırı bulunamadı")
                    continue

                if _tr_lower(norm_var) in _tr_lower(target_out_line):
                    errors.append(
                        f"{out_rel}:{idx+1} sızıntı (etiketlenmedi) {variant!r} -> {target_out_line!r}"
                    )
                    continue

                start = line.find(norm_var)
                end = start + len(norm_var)
                # Çıktı satırını etiket ve değişmez parçalara ayırarak tam konum eşlemesi yap
                parts = _TAG_RE.split(target_out_line)
                tags = _TAG_RE.findall(target_out_line)
                cursor = 0
                matched_tag = None
                for t_idx, tag in enumerate(tags):
                    lit_before = parts[t_idx]
                    if lit_before:
                        pos = line.find(lit_before, cursor)
                        if pos != -1:
                            cursor = pos + len(lit_before)
                    span_start = cursor
                    lit_after = parts[t_idx + 1] if t_idx + 1 < len(parts) else ""
                    if lit_after:
                        next_pos = line.find(lit_after, span_start)
                        span_end = next_pos if next_pos != -1 else len(line)
                    else:
                        # Son etiket satır sonuna kadar gider (veya adres il/ilçe ekli ise lit_after yakalar)
                        span_end = len(line)
                    if max(span_start, start) < min(span_end, end):
                        matched_tag = tag
                        break
                    cursor = span_end
                if not matched_tag:
                    errors.append(
                        f"{out_rel}:{idx+1} etiket yok ({variant!r}) -> {target_out_line!r}"
                    )
                    continue
                found_tags.append(matched_tag)

    return found_tags, errors


class _SenaryoTestTabani(unittest.TestCase):
    SENARYO: Senaryo
    _tmp_ctx: tempfile.TemporaryDirectory
    _tmp_root: str
    _src_dir: str
    _dest_dir: str
    _stats: Dict
    _src_before: Dict[str, bytes]
    _src_after: Dict[str, bytes]
    _out_texts: Dict[str, str]
    _file_map: Dict[str, str]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._tmp_ctx = tempfile.TemporaryDirectory(prefix=f"uyap_senaryo_{cls.SENARYO.ad}_")
        cls._tmp_root = cls._tmp_ctx.name
        cls._src_dir = os.path.join(cls._tmp_root, "kaynak_dava")
        cls._dest_dir = os.path.join(cls._tmp_root, "maskeli_cikti")
        os.makedirs(cls._src_dir, exist_ok=True)

        for rel_path, content in cls.SENARYO.dosyalar.items():
            full_path = os.path.join(cls._src_dir, rel_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as wf:
                wf.write(content)

        cls._src_before = _snapshot_tree(cls._src_dir)
        dest_out, stats = UyapRedactor.export_isolated_clean_folder(cls._src_dir, cls._dest_dir)
        cls._dest_dir = dest_out
        cls._stats = stats
        cls._src_after = _snapshot_tree(cls._src_dir)
        cls._out_texts = _collect_output_texts(cls._dest_dir)
        cls._file_map = _map_input_to_output_files(cls.SENARYO.dosyalar, cls._out_texts)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_ctx.cleanup()
        super().tearDownClass()

    def _check_sizinti(self) -> None:
        leaks: List[str] = []
        for secret in self.SENARYO.gizli:
            sec_low = _tr_lower(secret)
            for rel_path, content in sorted(self._out_texts.items()):
                if sec_low in _tr_lower(rel_path):
                    leaks.append(f"[DOSYA ADI] {rel_path}: sızan={secret!r}")
                for lineno, line in enumerate(content.splitlines(), 1):
                    check_line = _tr_lower(line)
                    for prot in self.SENARYO.korunan:
                        prot_low = _tr_lower(prot)
                        if sec_low in prot_low and len(prot_low) > len(sec_low):
                            check_line = check_line.replace(prot_low, " ")
                    if sec_low in check_line:
                        leaks.append(f"{rel_path}:{lineno} | sızan={secret!r} | satır={line!r}")
        if leaks:
            self.fail(
                f"[{self.SENARYO.ad}] {len(leaks)} sızıntı bulundu:\n" + "\n".join(leaks)
            )

    def _check_korunan(self) -> None:
        overmasked: List[str] = []
        for token in self.SENARYO.korunan:
            found_any = False
            for in_rel, in_raw in sorted(self.SENARYO.dosyalar.items()):
                if not in_rel.endswith((".md", ".txt")):
                    continue
                norm_in = UyapRedactor.normalize_spaces(in_raw)
                in_count = norm_in.count(token)
                if in_count == 0:
                    continue
                found_any = True
                out_rel = self._file_map.get(in_rel)
                if not out_rel or out_rel not in self._out_texts:
                    overmasked.append(f"{in_rel}: çıktı dosyası bulunamadı (korunan={token!r})")
                    continue
                out_text = self._out_texts[out_rel]
                out_count = out_text.count(token)
                if out_count < in_count:
                    in_lines = norm_in.splitlines()
                    out_lines = out_text.splitlines()
                    sample_diff = ""
                    for idx, il in enumerate(in_lines):
                        if token in il:
                            ol = out_lines[idx] if idx < len(out_lines) else "<satır yok>"
                            if token not in ol:
                                sample_diff = f" | girdi[{idx+1}]={il!r} -> çıktı={ol!r}"
                                break
                    overmasked.append(
                        f"{out_rel}: korunan={token!r} beklenen={in_count}, kalan={out_count}{sample_diff}"
                    )
            if not found_any:
                overmasked.append(f"Test tanım hatası: {token!r} hiçbir girdi belgesinde geçmiyor")
        if overmasked:
            self.fail(
                f"[{self.SENARYO.ad}] {len(overmasked)} fazla maskeleme (korunan değer bozuldu):\n"
                + "\n".join(overmasked)
            )

    def _check_kisiler(self) -> None:
        kisi_listesi = self._stats.get("kisi_listesi") or []
        actual_by_fold: Dict[str, List[Tuple[str, str]]] = {}
        for label, name in kisi_listesi:
            actual_by_fold.setdefault(_tr_fold(name), []).append((label, name))

        expected_by_fold = {_tr_fold(n): (n, r) for n, r in self.SENARYO.kisiler.items()}
        issues: List[str] = []

        for exp_fold, (exp_name, exp_role) in expected_by_fold.items():
            matches = actual_by_fold.get(exp_fold, [])
            if not matches:
                issues.append(f"EKSİK KİŞİ: {exp_name!r} (beklenen rol={exp_role})")
                continue
            if len(matches) > 1:
                issues.append(f"BÖLÜNMÜŞ KİŞİ: {exp_name!r} -> {matches}")
            for lab, raw_name in matches:
                if not lab.startswith(f"[{exp_role}_"):
                    issues.append(
                        f"YANLIŞ ROL: {exp_name!r} ({raw_name!r}) -> beklenen=[{exp_role}_*], gelen={lab}"
                    )

        for act_fold, entries in actual_by_fold.items():
            if act_fold not in expected_by_fold:
                for lab, raw_name in entries:
                    issues.append(f"FAZLA/YANLIŞ KİŞİ (false positive): {lab} = {raw_name!r}")

        if issues:
            self.fail(
                f"[{self.SENARYO.ad}] Kişi listesi uyuşmazlığı ({len(issues)} sorun):\n"
                + "\n".join(issues)
                + f"\nGerçek kisi_listesi={kisi_listesi}"
            )

    def _check_ayni_etiket(self) -> None:
        issues: List[str] = []
        for grp in self.SENARYO.ayni_etiket:
            grp_tags: Dict[str, List[str]] = {}
            for variant in grp:
                tags, errs = _extract_tags_for_variant(
                    self.SENARYO, self._file_map, self._out_texts, variant
                )
                for e in errs:
                    issues.append(f"Grup {grp}: {e}")
                for t in tags:
                    grp_tags.setdefault(t, []).append(variant)
            if len(grp_tags) > 1:
                issues.append(f"TUTARSIZ ETİKET grup={grp} -> etiketler={grp_tags}")
            elif not grp_tags and not any(f"Grup {grp}:" in x for x in issues):
                issues.append(f"Grup {grp} için hiç etiket çıkarılamadı")
        if issues:
            self.fail(
                f"[{self.SENARYO.ad}] Etiket tutarlılığı hatası ({len(issues)} sorun):\n"
                + "\n".join(issues)
            )

    def _check_satir_butunlugu(self) -> None:
        broken: List[str] = []
        for in_rel, in_raw in sorted(self.SENARYO.dosyalar.items()):
            if not in_rel.endswith((".md", ".txt")):
                continue
            out_rel = self._file_map.get(in_rel)
            if not out_rel or out_rel not in self._out_texts:
                broken.append(f"{in_rel}: çıktı dosyası bulunamadı")
                continue
            norm_in_lines = set(UyapRedactor.normalize_spaces(in_raw).splitlines())
            for lineno, out_line in enumerate(self._out_texts[out_rel].splitlines(), 1):
                if _TAG_RE.search(out_line):
                    continue
                if out_line not in norm_in_lines:
                    broken.append(f"{out_rel}:{lineno} | bozulan satır={out_line!r}")
        if broken:
            self.fail(
                f"[{self.SENARYO.ad}] {len(broken)} etiketsiz satır girdiyle uyuşmuyor:\n"
                + "\n".join(broken)
            )

    def _check_cikti_yapisi(self) -> None:
        issues: List[str] = []
        allowed_exts = {".md"}
        if any(p.endswith(".json") for p in self.SENARYO.dosyalar):
            allowed_exts.add(".json")
        if any(p.endswith(".txt") for p in self.SENARYO.dosyalar):
            allowed_exts.add(".txt")

        if UyapRedactor.REPORT_NAME not in self._out_texts:
            issues.append(f"Rapor dosyası eksik: {UyapRedactor.REPORT_NAME}")

        for out_rel in sorted(self._out_texts):
            ext = os.path.splitext(out_rel)[1].lower()
            if ext not in allowed_exts:
                issues.append(f"Beklenmeyen dosya uzantısı çıktıda: {out_rel}")

        for in_rel in sorted(self.SENARYO.dosyalar):
            if in_rel not in self._file_map:
                issues.append(f"Girdi dosyası çıktıya aktarılmadı: {in_rel}")

        if self._src_before != self._src_after:
            issues.append("Kaynak klasör değiştirilmiş!")

        root_entries = set(os.listdir(self._tmp_root))
        expected_entries = {os.path.basename(self._src_dir), os.path.basename(self._dest_dir)}
        extra = root_entries - expected_entries
        if extra:
            issues.append(f"Kaynak ve hedef dışında dosya/klasör oluştu: {sorted(extra)}")

        if issues:
            self.fail(
                f"[{self.SENARYO.ad}] Çıktı yapısı hatası:\n" + "\n".join(issues)
            )


def _make_scenario_test_class(senaryo: Senaryo) -> type:
    ad = senaryo.ad

    def test_sizinti(self):
        self._check_sizinti()

    def test_korunan(self):
        self._check_korunan()

    def test_kisiler(self):
        self._check_kisiler()

    def test_ayni_etiket(self):
        self._check_ayni_etiket()

    def test_satir_butunlugu(self):
        self._check_satir_butunlugu()

    def test_cikti_yapisi(self):
        self._check_cikti_yapisi()

    attrs = {
        "SENARYO": senaryo,
        f"test_{ad}_sizinti": test_sizinti,
        f"test_{ad}_korunan": test_korunan,
        f"test_{ad}_kisiler": test_kisiler,
        f"test_{ad}_ayni_etiket": test_ayni_etiket,
        f"test_{ad}_satir_butunlugu": test_satir_butunlugu,
        f"test_{ad}_cikti_yapisi": test_cikti_yapisi,
    }
    cls_name = f"TestSenaryo_{ad}"
    return type(cls_name, (_SenaryoTestTabani,), attrs)


for _sen in SENARYOLAR:
    _cls = _make_scenario_test_class(_sen)
    globals()[_cls.__name__] = _cls
del _sen, _cls


def _test_17_tam_beklenti(self: _SenaryoTestTabani) -> None:
    expected_kisi = {
        "[DAVACI_1]": "Ahmet Can Yılmaz",
        "[DAVALI_1]": "Mehmet Demir",
        "[DAVALI_2]": "Zeynep Demir",
        "[TANIK_1]": "Fatma Şahin",
        "[HAKİM_1]": "Murat Öz",
        "[KİŞİ_1]": "Ali Veli Kaya",
        "[KİŞİ_2]": "Kemal Aydın",
    }
    self.assertEqual(dict(self._stats["kisi_listesi"]), expected_kisi)

    dil_rel = "Dilekçeler/[DAVACI_1] dava dilekçesi.md"
    self.assertIn(dil_rel, self._out_texts)
    dil_out = self._out_texts[dil_rel]
    for exp_line in (
        "1. Davacı [DAVACI_1] ile davalı [DAVALI_1] arasında 12.03.2024 tarihinde sözleşme yapılmıştır. [DAVACI_1]'ın ödediği 125.000,00 TL iade edilmemiştir.",
        "2. [DAVACI_1] olay günü Ahmet Yılmaz Caddesi üzerindeki ofise gitmiş, [DAVALI_1]'e ihtar çekmiştir. Yılmaz o gün yalnızdı; Ahmet de bunu doğrular.",
        "3. Olayı tanık [TANIK_1] görmüştür. Tanık [TANIK_1]'in beyanı ektedir. [TANIK_1], Mehmet Demir İnşaat Ltd. Şti. çalışanıdır.",
        "5. Davalı [DAVALI_2], [DAVALI_1]'in eşidir. Baba adı: Hasan, Anne adı: Emine. Davacı Tarafından sunulan Dava Dilekçesi incelendi. Davalı Banka Genel Müdürlüğü cevap verdi. Tanık Olarak dinlenen kişi.",
        "6. Ayrıntı için bkz. [[DAVACI_1] dava dilekçesi](<[DAVACI_1] dava dilekçesi.md>)",
        "7. [KİŞİ_1] isimli komşu da oradaydı. Sanık Sıfatıyla ifadesi alınan [KİŞİ_2] suçlamayı reddetti.",
    ):
        self.assertIn(exp_line, dil_out)

    self.assertIn("tutanak.md", self._out_texts)
    tut_out = self._out_texts["tutanak.md"]
    for exp_line in (
        "DAVALI : [DAVALI_1]",
        'Tanık [TANIK_1] soruldu: "[DAVALI_1] parayı aldı" dedi. [DAVACI_1] haklıdır.',
        "Davacı Vekili Av. Ayşe Kaya söz aldı. Davalı [DAVALI_1] Bey duruşmaya gelmedi.",
    ):
        self.assertIn(exp_line, tut_out)

    self.assertIn("uyap-project.json", self._out_texts)
    proj = json.loads(self._out_texts["uyap-project.json"])
    self.assertEqual(
        proj,
        {
            "taraflar": [
                {"ad": "[DAVACI_1]", "sifat": "Davacı"},
                {"ad": "Demir İnşaat Ltd. Şti.", "sifat": "Davalı"},
            ]
        },
    )


TestSenaryo_17_ad_sirket_cakismasi.test_17_ad_sirket_cakismasi_tam_beklenti = _test_17_tam_beklenti


def _test_18_tam_beklenti(self: _SenaryoTestTabani) -> None:
    self.assertEqual(
        self._stats["kisi_listesi"],
        [
            ("[DAVACI_1]", "Selin Nur Aktaş"),
            ("[DAVALI_1]", "Orhan Aktaş"),
            ("[TANIK_1]", "Derya Koç"),
            ("[KİŞİ_1]", "Defne Aktaş"),
        ],
    )

    self.assertIn("dava.md", self._out_texts)
    self.assertIn("Ekler/Tanik_[TANIK_1]_beyani.md", self._out_texts)
    dava_out = self._out_texts["dava.md"]
    tanik_out = self._out_texts["Ekler/Tanik_[TANIK_1]_beyani.md"]

    # Bağlantı hedefi çıktıda var olan dosyayı göstermeli
    m_link = re.search(r'\[[^\]]*\[TANIK_1\][^\]]*\]\(([^)]+)\)', dava_out)
    self.assertIsNotNone(m_link, f"Bağlantı bulunamadı: {dava_out}")
    target = m_link.group(1).strip("<>")
    self.assertEqual(target, "Ekler/Tanik_[TANIK_1]_beyani.md")
    self.assertIn(target, self._out_texts)
    self.assertTrue(os.path.isfile(os.path.join(self._dest_dir, target)))

    # Beklenen satırlar
    self.assertIn("VEKİLİ : Av. Burak Tuna - Ankara Barosu [SİCİL_", dava_out)
    self.assertIn("müşterek çocuk [KİŞİ_1] 2018 doğumludur.", dava_out)
    self.assertIn(
        "Davalı, Aktaş Otomotiv Sanayi ve Ticaret Ltd. Şti. ortağıdır; "
        "şirket merkezi Ostim OSB 1234. Cad. No:8 Yenimahalle/Ankara adresindedir.",
        dava_out,
    )
    self.assertIn("[DAVACI_1]'un annesi Gülten Hanım ve tanık [TANIK_1]", dava_out)
    self.assertIn("[DAVALI_1] Bey aylık 85.000 TL gelir elde etmektedir. [DAVACI_1] Hanım çalışmamaktadır.", dava_out)
    self.assertIn('"[DAVALI_1] eşine bağırdı, Selin ağlıyordu. Koç Holding önünde karşılaştık."', tanik_out)

    # Koç Holding dışında "Koç" (ve diğer gizli değerler) geçmemeli
    for rel_path, content in self._out_texts.items():
        self.assertNotIn("Derya", content, rel_path)
        self.assertNotIn("Koc", content, rel_path)
        self.assertNotIn("Defne", content, rel_path)
        self.assertNotIn("23456", content, rel_path)
        without_holding = content.replace("Koç Holding", "")
        self.assertNotIn("Koç", without_holding, rel_path)
        self.assertNotIn("koç", _tr_lower(without_holding), rel_path)


TestSenaryo_18_aile_yakinlar.test_18_aile_yakinlar_tam_beklenti = _test_18_tam_beklenti


class TestTumSenaryolarAuditIsimKontrolu(unittest.TestCase):
    """Tüm sentetik senaryoların her iki moddaki çıktısında audit_output sızıntısı 0 olmalı."""

    def test_tum_senaryolar_varsayilan_mod_audit_sifir(self):
        import audit_output as A

        for sen in SENARYOLAR:
            with tempfile.TemporaryDirectory(prefix=f"uyap_audit_sen_{sen.ad}_") as tmp:
                src = os.path.join(tmp, "src")
                dest = os.path.join(tmp, "dest")
                for rel_path, content in sen.dosyalar.items():
                    fp = os.path.join(src, rel_path)
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    with open(fp, "w", encoding="utf-8") as wf:
                        wf.write(content)
                out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest)
                res = A.audit(src, out_dir)
                self.assertEqual(
                    res["leaks"]["person_name"],
                    [],
                    f"[{sen.ad}] varsayılan audit kişi adı sızıntısı buldu: {res['leaks']['person_name']}",
                )
                self.assertFalse(
                    A.summarize(res)[2],
                    f"[{sen.ad}] varsayılan audit genel sızıntı bildirdi: {res['leaks']}",
                )

    def test_tum_senaryolar_taraf_acik_mod_yargi_sizinti_ve_iki_mod_sicil_kapsami(self):
        """
        Tüm senaryolar hem varsayılan (mask_names=True, mask_judicial_names=True) hem de
        --taraf-isimlerini-koru (mask_names=False, mask_judicial_names=True) modunda dışa
        aktarılıp uyumlu audit ile denetlendiğinde 0 sızıntı vermeli; yargı unvanı + [SİCİL_]
        satırlarının aynı/komşu satırında [HAKİM_/[SAVCI_/[KÂTİP_ etiketi bulunmalıdır.
        """
        import audit_output as A

        jud_title_rx = re.compile(
            r"(?i)\b(?:h[aâ]kim\w*|ba[sş]kan\w*|üye\b|(?:cumhuriyet\s+)?(?:ba[sş])?savc[ıi]\w*|zab[ıi]t\s+k[aâ]tib\w*|k[aâ]ti[bp]\w*)"
        )
        jud_tag_rx = re.compile(r"\[(?:HAKİM|SAVCI|KÂTİP)_\d+\]")
        sicil_tag_rx = re.compile(r"\[SİCİL_\d+\]")
        missed_cases = []

        for sen in SENARYOLAR:
            for mask_names_flag in (True, False):
                with tempfile.TemporaryDirectory(prefix=f"uyap_mode_{mask_names_flag}_{sen.ad}_") as tmp:
                    src = os.path.join(tmp, "src")
                    dest = os.path.join(tmp, "dest")
                    for rel_path, content in sen.dosyalar.items():
                        fp = os.path.join(src, rel_path)
                        os.makedirs(os.path.dirname(fp), exist_ok=True)
                        with open(fp, "w", encoding="utf-8") as wf:
                            wf.write(content)
                    out_dir, _ = UyapRedactor.export_isolated_clean_folder(
                        src, dest, mask_names=mask_names_flag
                    )
                    res = A.audit(src, out_dir, mask_names=mask_names_flag)
                    self.assertEqual(
                        res["leaks"]["person_name"],
                        [],
                        f"[{sen.ad}] (mask_names={mask_names_flag}) audit ad sızıntısı buldu: {res['leaks']['person_name']}",
                    )
                    self.assertFalse(
                        A.summarize(res)[2],
                        f"[{sen.ad}] (mask_names={mask_names_flag}) audit genel sızıntı bildirdi: {res['leaks']}",
                    )
                    out_texts = _collect_output_texts(out_dir)
                    file_map = _map_input_to_output_files(sen.dosyalar, out_texts)
                    for in_rel, out_rel in sorted(file_map.items()):
                        if not out_rel.endswith(".md") or out_rel in ("DAVA_DÖNÜŞÜM_VE_GÜVENLİK_RAPORU.md", "INDEX.md"):
                            continue
                        o_lines = out_texts[out_rel].splitlines()
                        s_lines = sen.dosyalar[in_rel].splitlines()
                        for idx, ln in enumerate(o_lines):
                            if jud_title_rx.search(ln) and sicil_tag_rx.search(ln):
                                window = "\n".join(o_lines[max(0, idx - 1):min(len(o_lines), idx + 2)])
                                if not jud_tag_rx.search(window):
                                    src_line = s_lines[idx] if idx < len(s_lines) else ""
                                    stripped_titles = re.sub(
                                        r"(?i)\b(?:h[aâ]kim\w*|ba[sş]kan\w*|üye|cumhuriyet|ba[sş]?savc[ıi]\w*|zab[ıi]t|duru[sş]ma|k[aâ]ti[bp]\w*|sicil|no)\b|\d+",
                                        " ",
                                        src_line,
                                    )
                                    if re.search(r"[A-ZÇĞİÖŞÜ][a-zçğıöşüA-ZÇĞİÖŞÜ]+\s+[A-ZÇĞİÖŞÜ][a-zçğıöşüA-ZÇĞİÖŞÜ]+", stripped_titles):
                                        missed_cases.append(f"{sen.ad} (mask_names={mask_names_flag})/{out_rel}:{idx + 1}: {ln}")

        self.assertEqual(
            missed_cases,
            [],
            "Yargı unvanı + [SİCİL_] olup komşu satırlarda [HAKİM_/SAVCI_/KÂTİP_] bulunmayan satırlar:\n"
            + "\n".join(missed_cases),
        )


class TestSenaryo_20_yalniz_taramada_gecen_kisiler(unittest.TestCase):
    """Senaryo 20: 2 metinli belge + 2 taranmış belge ile OCR kişi keşfi, çapraz tutarlılık ve gürültü süzme."""

    def test_20_yalniz_taramada_gecen_kisiler(self):
        from unittest.mock import patch
        import audit_output as A

        metin_1 = (
            "DAVACI : Ayşe Kaya\n"
            "Yukarıda adı geçen davacı vekili tarafından Zeynep Arslan aleyhine dava açılmıştır.\n"
            "Ekli tutanakta tanık Murat Kılıç beyanlarına atıf yapılmaktadır.\n"
        )
        metin_2 = (
            "Durum özeti: Ayşe Kaya ile Zeynep Arslan arasındaki ihtilafta Murat Kılıç dinlenmiştir.\n"
            "Hasan Boz tekil referans olarak yalnızca bir kez anılmıştır.\n"
        )
        tarama_1_ocr = (
            "DAVALI : Zeynep Arslan\n"
            "Dosyada davacı Ayşe Kaya tarafından sunulan belgeler ve Zzzzz Xxx gibi gürültüler incelendi.\n"
            "DAVACI : Zzzzz Xxx\n"
        )
        tarama_2_ocr = (
            "Mahkeme huzurunda tanık Murat Kılıç yeminli olarak dinlendi.\n"
            "Ayrıca aynı celsede tanık Murat Kılıç kimlik tespiti yapıldı.\n"
            "Duruşma sırasında tanık Hasan Boz bir satırda anılmıştır.\n"
        )

        def _fake_ocr(fp: str) -> str:
            if fp.endswith("ek1_tarama.pdf"):
                return tarama_1_ocr
            if fp.endswith("ek2_tutanak.tif"):
                return tarama_2_ocr
            return ""

        with tempfile.TemporaryDirectory(prefix="uyap_sen20_") as tmp:
            src = os.path.join(tmp, "src")
            dest = os.path.join(tmp, "dest")
            cache = os.path.join(tmp, "ocr_cache")
            os.makedirs(src, exist_ok=True)
            with open(os.path.join(src, "dilekce.md"), "w", encoding="utf-8") as wf:
                wf.write(metin_1)
            with open(os.path.join(src, "ozet.txt"), "w", encoding="utf-8") as wf:
                wf.write(metin_2)
            with open(os.path.join(src, "ek1_tarama.pdf"), "wb") as wf:
                wf.write(b"%PDF-1.4\n%sahte tarama 1")
            with open(os.path.join(src, "ek2_tutanak.tif"), "wb") as wf:
                wf.write(b"fake-tiff-2")

            with patch.dict(os.environ, {"UYAP_OCR_CACHE_DIR": cache}, clear=False):
                with patch.object(UyapRedactor, "extract_scanned_raw", side_effect=_fake_ocr) as m_ocr:
                    out_dir, stats = UyapRedactor.export_isolated_clean_folder(src, dest)

            # Her taranmış belge tam 1 kez okunur
            self.assertEqual(m_ocr.call_count, 2)
            self.assertEqual(
                stats["kisi_listesi"],
                [
                    ("[DAVACI_1]", "Ayşe Kaya"),
                    ("[DAVALI_1]", "Zeynep Arslan"),
                    ("[TANIK_1]", "Murat Kılıç"),
                ],
            )

            out_contents = {}
            for root, _dirs, files in os.walk(out_dir):
                for fn in sorted(files):
                    if not fn.endswith((".md", ".txt")) or fn in (UyapRedactor.REPORT_NAME, "INDEX.md"):
                        continue
                    rel = os.path.relpath(os.path.join(root, fn), out_dir).replace("\\", "/")
                    with open(os.path.join(root, fn), encoding="utf-8") as rf:
                        out_contents[rel] = rf.read()

            self.assertIn("dilekce.md", out_contents)
            self.assertIn("ozet.txt", out_contents)
            self.assertIn("ek1_tarama.md", out_contents)
            self.assertIn("ek2_tutanak.md", out_contents)

            # Tüm çıktılarda taraf/tanık adları gizli, aynı etiket kullanılıyor
            for rel, txt in out_contents.items():
                self.assertNotIn("Ayşe Kaya", txt, rel)
                self.assertNotIn("Zeynep Arslan", txt, rel)
                self.assertNotIn("Murat Kılıç", txt, rel)
            self.assertIn("DAVACI : [DAVACI_1]", out_contents["dilekce.md"])
            self.assertIn("[DAVALI_1] aleyhine", out_contents["dilekce.md"])
            self.assertIn("[TANIK_1] beyanlarına", out_contents["dilekce.md"])
            self.assertIn("[DAVACI_1] ile [DAVALI_1] arasındaki ihtilafta [TANIK_1]", out_contents["ozet.txt"])
            self.assertIn("DAVALI : [DAVALI_1]", out_contents["ek1_tarama.md"])
            self.assertIn("davacı [DAVACI_1]", out_contents["ek1_tarama.md"])
            self.assertEqual(out_contents["ek2_tutanak.md"].count("[TANIK_1]"), 2)

            # Tek satır zayıf aday (Hasan Boz) ve gürültü (Zzzzz Xxx) korunur
            self.assertIn("Hasan Boz", out_contents["ozet.txt"])
            self.assertIn("Hasan Boz", out_contents["ek2_tutanak.md"])
            self.assertIn("Zzzzz Xxx", out_contents["ek1_tarama.md"])

            # Denetim aracı da sıfır kişi sızıntısı raporlar
            audit_res = A.audit(src, out_dir, ocr_cache=cache)
            self.assertEqual(audit_res["leaks"]["person_name"], [])


if __name__ == "__main__":
    unittest.main()
