#!/usr/bin/env python3
"""
100+ sentetik senaryolu uçtan uca maskeleme, yanlış yakalama, sızıntı, mod ve biçim doğrulama paketi.
Tüm veriler sentetiktir (dış kaynak/gerçek dosya kullanılmaz). Her senaryo pytest içinde ayrı test olarak çalışır.
"""

import io
import json
import os
import re
import signal
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import patch
from urllib.parse import unquote

import audit_output as A
import uyap_redactor as R
from uyap_redactor import UyapRedactor


def _tckn(seed: int) -> str:
    """Sentetik geçerli TCKN üreticisi (algoritmik sağlama tutarlı)."""
    base = 123456700 + (seed % 800000000)
    s = f"{base:09d}"
    d = [int(c) for c in s]
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    d11 = (sum(d) + d10) % 10
    return f"{s}{d10}{d11}"


def _iban(seed: int, grouped: bool = False) -> str:
    """Sentetik geçerli MOD-97 TR IBAN üreticisi."""
    body22 = f"00062{seed:017d}"[:22]
    num = int(body22 + "292700")
    chk = 98 - (num % 97)
    raw = f"TR{chk:02d}{body22}"
    if grouped:
        return " ".join(raw[i:i + 4] for i in range(0, len(raw), 4))
    return raw


def _write_fake_udf(path: str, content_text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    xml_body = (
        '<?xml version="1.0" encoding="UTF-8" ?>'
        f'<template format_id="1.8"><content><![CDATA[{content_text}]]></content></template>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.xml", xml_body.encode("utf-8"))


def _write_minimal_docx(path: str, paragraphs: List[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    p_xml = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{p_xml}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types.encode("utf-8"))
        zf.writestr("word/document.xml", doc_xml.encode("utf-8"))


def _write_fake_eyp(path: str, inner_files: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with tempfile.TemporaryDirectory() as stage:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for rel, payload in inner_files.items():
                if isinstance(payload, dict) and payload.get("__type__") == "udf":
                    p = os.path.join(stage, rel)
                    _write_fake_udf(p, payload["text"])
                    zf.write(p, rel)
                elif isinstance(payload, dict) and payload.get("__type__") == "docx":
                    p = os.path.join(stage, rel)
                    _write_minimal_docx(p, payload["paragraphs"])
                    zf.write(p, rel)
                else:
                    zf.writestr(rel, str(payload).encode("utf-8"))
            zf.writestr("PaketOzeti.xml", b"<ozet/>")
            zf.writestr("[Content_Types].xml", b"<Types/>")
            zf.writestr("_rels/.rels", b"<Relationships/>")


def _materialize_tree(src_dir: str, belgeler: Dict[str, Any]) -> None:
    for rel, spec in belgeler.items():
        fp = os.path.join(src_dir, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        if isinstance(spec, str):
            with open(fp, "w", encoding="utf-8", newline="") as wf:
                wf.write(spec)
        elif isinstance(spec, bytes):
            with open(fp, "wb") as wf:
                wf.write(spec)
        elif isinstance(spec, dict):
            kind = spec.get("__type__")
            if kind == "json":
                with open(fp, "w", encoding="utf-8") as wf:
                    json.dump(spec["data"], wf, ensure_ascii=False, indent=2)
            elif kind == "udf":
                _write_fake_udf(fp, spec["text"])
            elif kind == "docx":
                _write_minimal_docx(fp, spec["paragraphs"])
            elif kind == "eyp":
                _write_fake_eyp(fp, spec["entries"])
            else:
                raise ValueError(f"Bilinmeyen belge türü: {kind}")
        else:
            raise ValueError(f"Desteklenmeyen belge içeriği: {type(spec)}")


def _read_all_outputs(out_dir: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Döndürür: (doc_texts: rapor/index hariç metinler, all_texts: tüm metinler)."""
    doc_texts: Dict[str, str] = {}
    all_texts: Dict[str, str] = {}
    for root, _dirs, files in os.walk(out_dir):
        for fn in sorted(files):
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, out_dir).replace("\\", "/")
            if not fn.lower().endswith((".md", ".txt", ".json")):
                continue
            with open(fp, "r", encoding="utf-8") as rf:
                txt = rf.read()
            all_texts[rel] = txt
            if rel not in (UyapRedactor.REPORT_NAME, "INDEX.md"):
                doc_texts[rel] = txt
    return doc_texts, all_texts


# Önceden üretilmiş deterministik sentetik veriler
TC1 = _tckn(101)
TC2 = _tckn(202)
TC3 = _tckn(303)
TC4 = _tckn(404)
IBAN1 = _iban(11101)
IBAN2_GRP = _iban(22202, grouped=True)
IBAN3 = _iban(33303)


# Veri Tablosu: (id, kategori, belgeler, mod, olmali, olmamali[, ekstra])
# mod: "varsayilan" | "taraf_acik" | "yargi_acik" | "tum_acik" | custom dict
SENARYOLAR: List[Dict[str, Any]] = [
    # =========================================================================
    # KATEGORİ A: YARGI AD KEŞFİ (~32 senaryo)
    # =========================================================================
    {
        "id": "Y01_hakim_ascii_baslik",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "karar.md": "T.C. ANKARA 3. ASLİYE HUKUK MAHKEMESİ\nHakim : Mehmet Kaya (112233)\nKarar metni.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[SİCİL_1]"],
        "olmamali": ["Mehmet Kaya", "112233"],
    },
    {
        "id": "Y02_hakim_all_caps",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "tutanak.md": "T.C. İZMİR 2. TİCARET MAHKEMESİ\nHAKİM : AYŞE YILMAZ 112233\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[SİCİL_1]"],
        "olmamali": ["AYŞE YILMAZ", "Ayşe Yılmaz", "112233"],
    },
    {
        "id": "Y03_hakim_sicilsiz_mahkeme_baglami",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "tutanak.md": "T.C. BURSA 4. İŞ MAHKEMESİ\nEsas No: 2024/110\nHâkim : Mustafa Can\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["Mustafa Can"],
    },
    {
        "id": "Y04_hakimi_iyelik_eki",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "karar.md": "T.C. ANKARA 1. AİLE MAHKEMESİ\nMahkeme Hâkimi Zeynep Aksoy (234567) tarafından duruşma açıldı.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[SİCİL_1]"],
        "olmamali": ["Zeynep Aksoy", "234567"],
    },
    {
        "id": "Y05_heyet_baskan_uye_mahkeme_baglamli",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "heyet.md": (
                "T.C. İSTANBUL BÖLGE ADLİYE MAHKEMESİ 12. HUKUK DAİRESİ\n"
                "Esas No: 2024/50\n"
                "BAŞKAN : Kemal Demir (101010)\n"
                "ÜYE : Selin Yüksel (202020)\n"
                "ÜYE : Can Aydın (303030)\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["BAŞKAN : [HAKİM_1]", "ÜYE : [HAKİM_2]", "ÜYE : [HAKİM_3]"],
        "olmamali": ["Kemal Demir", "Selin Yüksel", "Can Aydın", "101010", "202020", "303030"],
    },
    {
        "id": "Y06_tutanak_yatay_tablosu",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "tablo.md": (
                "T.C. KONYA 1. ASLİYE TİCARET MAHKEMESİ\n"
                "| Unvan | Ad Soyad | Sicil |\n"
                "|---|---|---|\n"
                "| Hâkim | Murat Kaya | 112233 |\n"
                "| Zabıt Kâtibi | Seda Ak | 223344 |\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["| Hâkim | [HAKİM_1] | [SİCİL_1] |", "| Zabıt Kâtibi | [KÂTİP_1] | [SİCİL_2] |"],
        "olmamali": ["Murat Kaya", "Seda Ak", "112233", "223344"],
    },
    {
        "id": "Y07_imza_ad_ustte_e_imzali",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "imza_ust.md": (
                "T.C. ADANA 2. ASLİYE CEZA MAHKEMESİ\n"
                "Gereği düşünüldü, hüküm kuruldu.\n"
                "Mehmet Kaya\n"
                "Hâkim 112233\n"
                "e-imzalıdır\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[SİCİL_1]"],
        "olmamali": ["Mehmet Kaya", "112233"],
    },
    {
        "id": "Y08_imza_ad_altta_e_imzali",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "imza_alt.md": (
                "T.C. ANTALYA 5. HUKUK MAHKEMESİ\n"
                "Karar tarihinde tefhim olundu.\n"
                "Hâkim (112233)\n"
                "Mehmet Kaya\n"
                "e-imzalıdır\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[SİCİL_1]"],
        "olmamali": ["Mehmet Kaya", "112233"],
    },
    {
        "id": "Y09_cift_sutun_udf_imza_bloku",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "cift_sutun.md": (
                "T.C. ESKİŞEHİR 1. AĞIR CEZA MAHKEMESİ\n"
                "Hâkim (445566)        Zabıt Kâtibi (556677)\n"
                "Ayşe Yılmaz           Zeynep Çelik\n"
                "e-imzalıdır           e-imzalıdır\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[KÂTİP_1]"],
        "olmamali": ["Ayşe Yılmaz", "Zeynep Çelik", "445566", "556677"],
    },
    {
        "id": "Y10_iddianame_savci_bloku",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "iddianame.md": (
                "T.C. ANKARA CUMHURİYET BAŞSAVCILIĞI\n"
                "Soruşturma No: 2024/555\n"
                "Düzenleyen C. Savcısı : Faruk Öztürk (445566)\n"
                "Şüpheli hakkında kamu davası açılması talep olunur.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[SİCİL_1]"],
        "olmamali": ["Faruk Öztürk", "445566"],
    },
    {
        "id": "Y11_cumhuriyet_savcisi_uc_kelime",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "mütalaa.md": "T.C. İSTANBUL CUMHURİYET BAŞSAVCILIĞI\nCUMHURİYET SAVCISI : Mehmet Ali Polat (556677)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[SİCİL_1]"],
        "olmamali": ["Mehmet Ali Polat", "556677"],
    },
    {
        "id": "Y12_sorusturma_savcisi",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "sorusturma.md": "T.C. İZMİR CUMHURİYET BAŞSAVCILIĞI\nSoruşturma Savcısı : Orhan Demirci (667788)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[SİCİL_1]"],
        "olmamali": ["Orhan Demirci", "667788"],
    },
    {
        "id": "Y13_c_savcisi_kisaltma",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "csavci.md": "T.C. MERSİN 3. ASLİYE CEZA MAHKEMESİ\nC. Savcısı : Hasan Eren (778899)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[SİCİL_1]"],
        "olmamali": ["Hasan Eren", "778899"],
    },
    {
        "id": "Y14_cumhuriyet_bassavcisi",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "bassavci.md": "T.C. SAMSUN CUMHURİYET BAŞSAVCILIĞI\nCumhuriyet Başsavcısı : Engin Aktaş 889900\n",
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[SİCİL_1]"],
        "olmamali": ["Engin Aktaş", "889900"],
    },
    {
        "id": "Y15_katip_ascii_i",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "katip.md": "T.C. TRABZON 1. HUKUK MAHKEMESİ\nKatip : Onur Yüksel (334455)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[KÂTİP_1]", "[SİCİL_1]"],
        "olmamali": ["Onur Yüksel", "334455"],
    },
    {
        "id": "Y16_katip_sapkalı_sicilsiz_bosluk",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "katip2.md": "T.C. KAYSERİ 2. İŞ MAHKEMESİ\nKâtip : Emine Tunç 445566\n",
        },
        "mod": "varsayilan",
        "olmali": ["[KÂTİP_1]", "[SİCİL_1]"],
        "olmamali": ["Emine Tunç", "445566"],
    },
    {
        "id": "Y17_zabit_katibi_all_caps",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "zabit.md": "T.C. GAZİANTEP 1. SULH HUKUK MAHKEMESİ\nZABIT KATİBİ : YASEMİN ÇELİK (556677)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[KÂTİP_1]", "[SİCİL_1]"],
        "olmamali": ["YASEMİN ÇELİK", "Yasemin Çelik", "556677"],
    },
    {
        "id": "Y18_durusma_katibi",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "durusma_k.md": "T.C. DİYARBAKIR 2. İŞ MAHKEMESİ\nDuruşma Kâtibi : Tuna Aksoy (667788)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[KÂTİP_1]", "[SİCİL_1]"],
        "olmamali": ["Tuna Aksoy", "667788"],
    },
    {
        "id": "Y19_ocr_all_caps_ascii_unvanlar",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "ocr_benzeri.md": (
                "T.C. KOCAELİ 4. CEZA MAHKEMESİ\n"
                "CUMHURIYET SAVCISI : TARIK AYDIN 121212\n"
                "ZABIT KATIBI : DENIZ KOC 343434\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[KÂTİP_1]"],
        "olmamali": ["TARIK AYDIN", "DENIZ KOC", "121212", "343434"],
    },
    {
        "id": "Y20_soyad_ad_sirasi",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "ters_ad.md": (
                "T.C. ANKARA 2. ASLİYE HUKUK MAHKEMESİ\n"
                "HÂKİM : KAYA Mehmet (112233)\n"
                "Hâkim Mehmet Kaya duruşmaya devamla karar verdi.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["KAYA Mehmet", "Mehmet Kaya", "112233"],
    },
    {
        "id": "Y21_uc_dort_parcali_yargi_adlari",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "uzun_adlar.md": (
                "T.C. İSTANBUL 6. AİLE MAHKEMESİ\n"
                "Hâkim : Ahmet Can Demirtaş (112233)\n"
                "Cumhuriyet Savcısı : Ayşe Zeynep Nur Kaya (223344)\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[SAVCI_1]"],
        "olmamali": ["Ahmet Can Demirtaş", "Ayşe Zeynep Nur Kaya"],
    },
    {
        "id": "Y22_turkce_cekim_ekleri",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "ekler.md": (
                "T.C. İZMİR 1. TİCARET MAHKEMESİ\n"
                "HÂKİM : Mehmet Kaya (112233)\n"
                "CUMHURİYET SAVCISI : Ali Veli (223344)\n"
                "Dosya Hâkim Mehmet Kaya'nın önüne geldi; itiraz Mehmet Kaya'ya iletildi ve Ali Veli'nin mütalaası alındı.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]'nın", "[HAKİM_1]'ya", "[SAVCI_1]'nin"],
        "olmamali": ["Mehmet Kaya", "Ali Veli"],
    },
    {
        "id": "Y23_ayni_yargi_kisisinin_farkli_yazimlari",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "yazimlar.md": (
                "T.C. ANKARA 5. İŞ MAHKEMESİ\n"
                "HÂKİM : MEHMET KAYA (112233)\n"
                "Ara kararda Hâkim Mehmet Kaya imzası yer almakta olup M. Kaya kararı onadı.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["MEHMET KAYA", "Mehmet Kaya", "M. Kaya", "[HAKİM_2]"],
    },
    {
        "id": "Y24_iki_farkli_hakim_numaralandirma",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "devir.md": (
                "T.C. SAKARYA 1. ASLİYE HUKUK MAHKEMESİ\n"
                "Celse 1 - HÂKİM : Mehmet Kaya (112233)\n"
                "Celse 2 - HÂKİM : Ayşe Demir (223344)\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[HAKİM_2]"],
        "olmamali": ["Mehmet Kaya", "Ayşe Demir", "112233", "223344"],
    },
    {
        "id": "Y25_uyap_project_json_yargi_rolleri",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "dava.md": "T.C. BURSA 1. HUKUK MAHKEMESİ\nDosyada Mehmet Kaya ve Ali Veli görevlidir.\n",
            "uyap-project.json": {
                "__type__": "json",
                "data": {
                    "taraflar": [
                        {"sifat": "Hâkim", "adSoyad": "Mehmet Kaya"},
                        {"sifat": "Cumhuriyet Savcısı", "adSoyad": "Ali Veli"},
                        {"sifat": "Zabıt Kâtibi", "adSoyad": "Fatma Tunç"},
                    ]
                },
            },
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[SAVCI_1]", "[KÂTİP_1]"],
        "olmamali": ["Mehmet Kaya", "Ali Veli", "Fatma Tunç"],
    },
    {
        "id": "Y26_dosya_adinda_hakim_adi",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "Hakim_Mehmet_Kaya_Karar.md": "T.C. ANKARA 3. İŞ MAHKEMESİ\nHÂKİM : Mehmet Kaya (112233)\nKarar.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["Mehmet Kaya", "Mehmet", "Kaya"],
        "check_filenames": True,
    },
    {
        "id": "Y27_markdown_link_ve_index_yargi_adi",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "Hakim_Mehmet_Kaya_Karar.md": "T.C. ANKARA 3. İŞ MAHKEMESİ\nHÂKİM : Mehmet Kaya (112233)\n",
            "INDEX.md": "# Dizin\n- [Hakim Mehmet Kaya Kararı](Hakim_Mehmet_Kaya_Karar.md)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["Mehmet Kaya", "Mehmet", "Kaya"],
        "check_index_links": True,
    },
    {
        "id": "Y28_belgeler_arasi_yargi_tutarliligi",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "01_tutanak.md": "T.C. MANİSA 1. HUKUK MAHKEMESİ\nHÂKİM : Mehmet Kaya (112233)\n",
            "02_gerekceli.md": "İmzalayan Mehmet Kaya kararı tebliğ etti.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["Mehmet Kaya", "112233"],
    },
    {
        "id": "Y29_taraf_acik_modda_yargi_yine_maskeli",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "tutanak.md": (
                "T.C. ANKARA 1. TİCARET MAHKEMESİ\n"
                "DAVACI : Ahmet Çelik\n"
                "HÂKİM : Mehmet Kaya (112233)\n"
                "CUMHURİYET SAVCISI : Ali Veli (223344)\n"
                "ZABIT KÂTİBİ : Fatma Tunç (334455)\n"
            ),
        },
        "mod": "taraf_acik",
        "olmali": ["Ahmet Çelik", "[HAKİM_1]", "[SAVCI_1]", "[KÂTİP_1]"],
        "olmamali": ["Mehmet Kaya", "Ali Veli", "Fatma Tunç", "112233", "223344", "334455"],
    },
    {
        "id": "Y30_nobetci_savci_savci_vekili",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "nobet.md": (
                "T.C. DENİZLİ CUMHURİYET BAŞSAVCILIĞI\n"
                "Nöbetçi Savcı : Kemal Tunç (123123)\n"
                "Savcı Vekili : Burcu Şen (321321)\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[SAVCI_2]"],
        "olmamali": ["Kemal Tunç", "Burcu Şen", "123123", "321321"],
    },
    {
        "id": "Y31_duzyazi_hakim_ve_savci_ati",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "duzyazi.md": (
                "T.C. AYDIN 2. ASLİYE CEZA MAHKEMESİ\n"
                "Duruşmada Cumhuriyet Savcısı Ali Veli mütalaasını açıkladı; Mahkeme Hâkimi Mehmet Kaya ara karar kurdu.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[SAVCI_1]", "[HAKİM_1]"],
        "olmamali": ["Ali Veli", "Mehmet Kaya"],
    },
    {
        "id": "Y32_markdown_bold_ve_liste_yargi_baslik",
        "kategori": "yargi_ad_kesfi",
        "belgeler": {
            "md_bicim.md": (
                "T.C. MUĞLA 1. SULH HUKUK MAHKEMESİ\n"
                "**HÂKİM :** Mehmet Kaya (112233)\n"
                "- **Zabıt Kâtibi:** Seda Ak (223344)\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[KÂTİP_1]"],
        "olmamali": ["Mehmet Kaya", "Seda Ak", "112233", "223344"],
    },

    # =========================================================================
    # KATEGORİ B: YANLIŞ YAKALAMA (KORUNMALI) (~26 senaryo)
    # =========================================================================
    {
        "id": "F01_arac_plakalari",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "plaka.md": "Olayda 34 ABC 123, 06 XY 9999 ve 35 K 4567 plakalı araçlar çarpıştı.\n",
        },
        "mod": "varsayilan",
        "olmali": ["34 ABC 123", "06 XY 9999", "35 K 4567"],
        "olmamali": ["[TCKN_", "[TEL_", "[SİCİL_"],
    },
    {
        "id": "F02_ada_parsel_pafta",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "tapu.md": "Taşınmaz: 1245 Ada 8 Parsel, Ada No: 312, Parsel No: 14, 4210/3 parsel sayılı yer.\n",
        },
        "mod": "varsayilan",
        "olmali": ["1245 Ada 8 Parsel", "Ada No: 312", "Parsel No: 14", "4210/3 parsel"],
        "olmamali": ["[ADRES_", "[SİCİL_"],
    },
    {
        "id": "F03_barkod_evrak_fatura_dekont_yevmiye_tapu",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "numaralar.md": (
                "Barkod No: 8691234567890\n"
                "Evrak No: 20240011223\n"
                "Fatura No: FT20240000123\n"
                "Dekont No: 99887766\n"
                "Yevmiye No: 14562\n"
                "Tapu Cilt: 12 Sayfa: 34\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["8691234567890", "20240011223", "FT20240000123", "99887766", "14562"],
        "olmamali": ["[TCKN_", "[HESAP_", "[SİCİL_", "[SERİ_NO_"],
    },
    {
        "id": "F04_para_tutarlari",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "tutar.md": "Toplam 125.000,00 TL, 1.234.567,89 TL, 112233,00 TL ve 450000 USD alacak mevcuttur.\n",
        },
        "mod": "varsayilan",
        "olmali": ["125.000,00 TL", "1.234.567,89 TL", "112233,00 TL", "450000 USD"],
        "olmamali": ["[TCKN_", "[HESAP_", "[SİCİL_"],
    },
    {
        "id": "F05_tarih_ve_saat",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "tarih.md": "Duruşma 14.03.2024, 2024-03-14 ve 14/11/2025 saat 10:30 olarak belirlendi.\n",
        },
        "mod": "varsayilan",
        "olmali": ["14.03.2024", "2024-03-14", "14/11/2025 saat 10:30"],
        "olmamali": ["[TCKN_", "[TEL_"],
    },
    {
        "id": "F06_esas_karar_sorusturma_no",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "esas.md": (
                "Esas No: 2024/123456 E.\n"
                "Karar No: 2025/654321 K.\n"
                "Soruşturma No: 2024/112233\n"
                "Talimat No: 2023/987654\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["2024/123456 E.", "2025/654321 K.", "2024/112233", "2023/987654"],
        "olmamali": ["[SİCİL_", "[HESAP_"],
    },
    {
        "id": "F07_kanun_maddeleri",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "kanun.md": "6100 sayılı HMK m. 119, 6098 sayılı TBK md. 49 ve TCK 157/1 uyarınca.\n",
        },
        "mod": "varsayilan",
        "olmali": ["6100 sayılı HMK m. 119", "6098 sayılı TBK md. 49", "TCK 157/1"],
        "olmamali": ["[TCKN_", "[KİŞİ_"],
    },
    {
        "id": "F08_sirket_unvanlari",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "sirket.md": (
                "DAVALI : Örnek İnşaat San. ve Tic. A.Ş.\n"
                "Ahmet Kaya Mimarlık Ltd. Şti. ve Bosphorus Metal Ticaret A.Ş. fatura düzenledi.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Örnek İnşaat San. ve Tic. A.Ş.", "Ahmet Kaya Mimarlık Ltd. Şti.", "Bosphorus Metal Ticaret A.Ş."],
        "olmamali": ["[DAVALI_", "[KİŞİ_"],
    },
    {
        "id": "F09_sirket_antet_adresi",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "antet.md": "Davalı şirketin adresi: Maslak Mahallesi Büyükdere Caddesi No: 12 Sarıyer/İstanbul (Anteti).\n",
        },
        "mod": "varsayilan",
        "olmali": ["Maslak Mahallesi Büyükdere Caddesi No: 12 Sarıyer/İstanbul"],
        "olmamali": ["[ADRES_"],
    },
    {
        "id": "F10_oda_ve_baro_adresi",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "kurum_adres.md": (
                "Ankara Ticaret Odası: Atatürk Bulvarı No:21 Çankaya/Ankara\n"
                "İstanbul Barosu Başkanlığı: İstiklal Cad. No:15 Beyoğlu/İstanbul\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Atatürk Bulvarı No:21 Çankaya/Ankara", "İstiklal Cad. No:15 Beyoğlu/İstanbul"],
        "olmamali": ["[ADRES_"],
    },
    {
        "id": "F11_mahkeme_adliye_adresi",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "adliye.md": "Ankara Adliyesi Sıhhiye Atatürk Bulvarı No: 50 Çankaya/Ankara\n",
        },
        "mod": "varsayilan",
        "olmali": ["Atatürk Bulvarı No: 50 Çankaya/Ankara"],
        "olmamali": ["[ADRES_"],
    },
    {
        "id": "F12_banka_ptt_noter_adresi",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "noter_banka.md": (
                "Örnek Bankası Genel Müdürlüğü Barbaros Bulvarı No: 40 Beşiktaş/İstanbul\n"
                "Kadıköy 5. Noterliği Bahariye Cad. No:18 Kadıköy/İstanbul\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Barbaros Bulvarı No: 40 Beşiktaş/İstanbul", "Bahariye Cad. No:18 Kadıköy/İstanbul"],
        "olmamali": ["[ADRES_"],
    },
    {
        "id": "F13_olay_kaza_kesif_yeri",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "olay_yeri.md": (
                "Suç mahalli: Barbaros Mah. 10. Sok. No:5 Beşiktaş/İstanbul\n"
                "Kaza mahalli: İzmir Yolu 12. Km Nilüfer/Bursa\n"
                "Keşif yeri: Çamlıca Mah. Lale Cad. No:8 Üsküdar/İstanbul\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Barbaros Mah. 10. Sok. No:5", "İzmir Yolu 12. Km Nilüfer/Bursa", "Çamlıca Mah. Lale Cad. No:8"],
        "olmamali": ["[ADRES_"],
    },
    {
        "id": "F14_sabit_hat_telefonlari",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "sabit_tel.md": "Şirket santrali: 0212 333 44 55, 0312 415 20 30 ve (0216) 555 12 34.\n",
        },
        "mod": "varsayilan",
        "olmali": ["0212 333 44 55", "0312 415 20 30", "(0216) 555 12 34"],
        "olmamali": ["[TEL_"],
    },
    {
        "id": "F15_ticaret_sicil_no",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "ticsicil.md": "Ticaret Sicil No: 123456-5, İstanbul Ticaret Sicili No: 654321.\n",
        },
        "mod": "varsayilan",
        "olmali": ["123456-5", "654321"],
        "olmamali": ["[SİCİL_", "[HESAP_"],
    },
    {
        "id": "F16_sasi_ve_motor_no",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "arac_no.md": "Aracın Şasi No: WVWZZZ1KZ8W123456, Motor No: BKC123456 kayıtlıdır.\n",
        },
        "mod": "varsayilan",
        "olmali": ["WVWZZZ1KZ8W123456", "BKC123456"],
        "olmamali": ["[SERİ_NO_", "[SİCİL_"],
    },
    {
        "id": "F17_hakim_ortak_sirket_belgesi",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "ortaklik.md": (
                "ÖRNEK YAPI A.Ş. OLAĞAN GENEL KURUL TUTANAĞI\n"
                "Hâkim ortak Mehmet Kaya toplantıya katıldı.\n"
                "Üye : Can Demir\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Mehmet Kaya", "Can Demir"],
        "olmamali": ["[HAKİM_", "[KİŞİ_"],
    },
    {
        "id": "F18_sirket_yonetim_kurulu_baskani",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "yk.md": "Yönetim Kurulu Başkanı Can Demir ve Şirket Başkanı Ahmet Öz imzaları alındı.\n",
        },
        "mod": "varsayilan",
        "olmali": ["Can Demir", "Ahmet Öz"],
        "olmamali": ["[HAKİM_", "[KİŞİ_"],
    },
    {
        "id": "F19_divan_ve_toplanti_baskani",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "divan.md": (
                "GENEL KURUL TUTANAĞI\n"
                "Divan Başkanı : Hasan Aksoy\n"
                "Toplantı Başkanı : Emre Koç\n"
                "Üye : Can Demir\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Hasan Aksoy", "Emre Koç", "Can Demir"],
        "olmamali": ["[HAKİM_"],
    },
    {
        "id": "F20_ihale_komisyon_baskani_uyesi",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "ihale.md": (
                "İHALE KOMİSYON KARARI\n"
                "Komisyon Başkanı : Emre Koç\n"
                "Komisyon Üyesi : Cemre Tan\n"
                "Üye : Deniz Arslan\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Emre Koç", "Cemre Tan", "Deniz Arslan"],
        "olmamali": ["[HAKİM_"],
    },
    {
        "id": "F21_yer_adi_katip_celebi_hakimiyet",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "yerler.md": (
                "Olay yeri: Katip Çelebi Mahallesi Hakimiyet Caddesi No: 10 Beyoğlu/İstanbul\n"
                "Katip Çelebi Kültür Merkezi önünde tutanak tutuldu.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Katip Çelebi Mahallesi", "Hakimiyet Caddesi", "Katip Çelebi Kültür Merkezi"],
        "olmamali": ["[KÂTİP_", "[HAKİM_", "[ADRES_"],
    },
    {
        "id": "F22_sozcuk_cakismasi_hakimiyet_savcilik_baskanlik",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "sozcukler.md": (
                "T.C. ANKARA 1. ASLİYE CEZA MAHKEMESİ\n"
                "Bölgede hakimiyet kurulması iddiası ile Savcılık Makamı tarafından Başkanlık Divanı yazısı sunuldu.\n"
                "Hâkimiyet ve Başsavcılık yazışmaları incelendi.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["hakimiyet kurulması", "Savcılık Makamı", "Başkanlık Divanı"],
        "olmamali": ["[HAKİM_", "[SAVCI_", "[KÂTİP_"],
    },
    {
        "id": "F23_avukat_vekil_mudafi_acik",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "avukat.md": (
                "VEKİLİ : Av. Ayşe Yılmaz\n"
                "Sanık Müdafii : Av. Kemal Öz\n"
                "Davacı Vekili Canan Demir duruşmaya katıldı.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["Av. Ayşe Yılmaz", "Av. Kemal Öz", "Canan Demir"],
        "olmamali": ["[KİŞİ_", "[DAVACI_"],
    },
    {
        "id": "F24_bilirkisi_arabulucu_acik",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "bilirkisi.md": "Bilirkişi Prof. Dr. Hasan Boz ve Arabulucu Deniz Kara raporu imzaladı.\n",
        },
        "mod": "varsayilan",
        "olmali": ["Hasan Boz", "Deniz Kara"],
        "olmamali": ["[KİŞİ_", "[TANIK_"],
    },
    {
        "id": "F25_mubasir_teblig_memuru_acik",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "gorevli.md": "Mübaşir Veli Ak çağrı yaptı; Tebliğ Memuru Murat Yıldız mazbata düzenledi.\n",
        },
        "mod": "varsayilan",
        "olmali": ["Veli Ak", "Murat Yıldız"],
        "olmamali": ["[KİŞİ_", "[KÂTİP_"],
    },
    {
        "id": "F26_anne_baba_adlari_acik",
        "kategori": "yanlis_yakalama",
        "belgeler": {
            "nufus.md": "Anne adı: Ayşe, Baba adı: Mustafa olarak kayıtlıdır.\n",
        },
        "mod": "varsayilan",
        "olmali": ["Anne adı: Ayşe", "Baba adı: Mustafa"],
        "olmamali": ["[KİŞİ_"],
    },

    # =========================================================================
    # KATEGORİ C: SIZINTI (MASKELENMELİ) (~26 senaryo)
    # =========================================================================
    {
        "id": "S01_tckn_bitisik",
        "kategori": "sizinti",
        "belgeler": {"tckn1.md": f"İlgili kişi numarası {TC1} olup dosyaya işlendi.\n"},
        "mod": "varsayilan",
        "olmali": ["[TCKN_1]"],
        "olmamali": [TC1],
    },
    {
        "id": "S02_tckn_bosluklu_ve_tireli",
        "kategori": "sizinti",
        "belgeler": {
            "tckn2.md": (
                f"Kimlik No: {TC1[:3]} {TC1[3:6]} {TC1[6:9]} {TC1[9:]}\n"
                f"TCKN: {TC2[:3]}-{TC2[3:6]}-{TC2[6:9]}-{TC2[9:]}\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[TCKN_1]", "[TCKN_2]"],
        "olmamali": [TC1[:6], TC2[:6]],
    },
    {
        "id": "S03_tckn_etiketli_ve_tekrarli",
        "kategori": "sizinti",
        "belgeler": {
            "tckn3.md": f"T.C. Kimlik No: {TC1}\nAynı numara TCKN: {TC1} ve {TC2}.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[TCKN_1]", "[TCKN_2]"],
        "olmamali": [TC1, TC2],
    },
    {
        "id": "S04_tckn_soft_hyphen_ve_satir_kirilmasi",
        "kategori": "sizinti",
        "belgeler": {
            "tckn4.md": f"TCKN: {TC1[:6]}\u00ad{TC1[6:]}\nT.C. Kimlik No:\n{TC2[:5]}\n{TC2[5:]}\n",
        },
        "mod": "varsayilan",
        "olmali": ["[TCKN_1]", "[TCKN_2]"],
        "olmamali": [TC1, TC2, TC1[:6], TC2[5:]],
    },
    {
        "id": "S05_tckn_ptt_yildizli",
        "kategori": "sizinti",
        "belgeler": {
            "ptt.md": f"PTT Teslimat TCKN : {TC1[:3]}*****{TC1[-3:]}\nKısmi T.C. Kimlik No: {TC2[:3]}***{TC2[-3:]}\n",
        },
        "mod": "varsayilan",
        "olmali": ["[TCKN_"],
        "olmamali": ["*****", "***"],
    },
    {
        "id": "S06_kisi_ikamet_adresi",
        "kategori": "sizinti",
        "belgeler": {
            "ikamet.md": "İkametgah Adresi: Caferağa Mah. Moda Cad. No:12 D:3 Kadıköy/İstanbul\n",
        },
        "mod": "varsayilan",
        "olmali": ["[ADRES_1]", "Kadıköy/İstanbul"],
        "olmamali": ["Caferağa Mah.", "Moda Cad.", "No:12"],
    },
    {
        "id": "S07_tebligat_adresi",
        "kategori": "sizinti",
        "belgeler": {
            "tebligat.md": "Tebligat Adresi: Bahçelievler Mah. 7. Sok. No: 18 Çankaya/Ankara\n",
        },
        "mod": "varsayilan",
        "olmali": ["[ADRES_1]", "Çankaya/Ankara"],
        "olmamali": ["Bahçelievler Mah.", "7. Sok.", "No: 18"],
    },
    {
        "id": "S08_sirket_yetkilisi_kisi_adresi",
        "kategori": "sizinti",
        "belgeler": {
            "yetkili_adr.md": "Davalı şirket yetkilisi Ahmet Çelik'in adresi: Feneryolu Mah. Bağdat Cad. No: 110 D:9 Kadıköy/İstanbul\n",
        },
        "mod": "varsayilan",
        "olmali": ["[ADRES_1]", "Kadıköy/İstanbul"],
        "olmamali": ["Feneryolu Mah.", "Bağdat Cad.", "No: 110"],
    },
    {
        "id": "S09_sirket_ortagi_adresi",
        "kategori": "sizinti",
        "belgeler": {
            "ortak_adr.md": "Şirket ortağı Mehmet Demir ikamet adresi: Etiler Mah. Nispetiye Cad. No: 8 Beşiktaş/İstanbul\n",
        },
        "mod": "varsayilan",
        "olmali": ["[ADRES_1]", "Beşiktaş/İstanbul"],
        "olmamali": ["Etiler Mah.", "Nispetiye Cad.", "No: 8"],
    },
    {
        "id": "S10_satira_bolunmus_adres",
        "kategori": "sizinti",
        "belgeler": {
            "boluk_adr.md": "Adres: Yıldız Mah. Çiçek Sok.\nNo: 4 D: 2 Beşiktaş/İstanbul\n",
        },
        "mod": "varsayilan",
        "olmali": ["[ADRES_1]"],
        "olmamali": ["Yıldız Mah.", "Çiçek Sok.", "No: 4"],
    },
    {
        "id": "S11_cep_telefonu_bitisik_bosluklu",
        "kategori": "sizinti",
        "belgeler": {
            "gsm1.md": "GSM: 05321234567 ve ikinci hat: 0533 444 55 66.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[TEL_1]", "[TEL_2]"],
        "olmamali": ["05321234567", "0533 444 55 66"],
    },
    {
        "id": "S12_cep_telefonu_parantez_ve_90",
        "kategori": "sizinti",
        "belgeler": {
            "gsm2.md": "Telefon: 0(542) 666 77 88 ve +90 555 777 88 99.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[TEL_1]", "[TEL_2]"],
        "olmamali": ["542", "555 777"],
    },
    {
        "id": "S13_iban_bitisik_ve_gruplu",
        "kategori": "sizinti",
        "belgeler": {
            "iban.md": f"Alıcı IBAN: {IBAN1}\nİkinci IBAN: {IBAN2_GRP}\n",
        },
        "mod": "varsayilan",
        "olmali": ["[IBAN_1]", "[IBAN_2]"],
        "olmamali": [IBAN1, IBAN2_GRP, IBAN1[-8:]],
    },
    {
        "id": "S14_iban_satira_bolunmus",
        "kategori": "sizinti",
        "belgeler": {
            "iban_split.md": f"IBAN:\n{IBAN1[:12]}\n{IBAN1[12:]}\n",
        },
        "mod": "varsayilan",
        "olmali": ["[IBAN_1]"],
        "olmamali": [IBAN1[:12], IBAN1[12:]],
    },
    {
        "id": "S15_hesap_ve_musteri_no",
        "kategori": "sizinti",
        "belgeler": {
            "hesap.md": "Gönderen Hesap No: 77192038, Müşteri No: 88991122.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HESAP_1]", "[HESAP_2]"],
        "olmamali": ["77192038", "88991122"],
    },
    {
        "id": "S16_kart_no_tam_ve_kismi",
        "kategori": "sizinti",
        "belgeler": {
            "kart.md": "Kredi Kartı : 4532 1111 2222 3337\nKısmi Kart : 4532 **** **** 3337\n",
        },
        "mod": "varsayilan",
        "olmali": ["[KART_1]"],
        "olmamali": ["4532 1111 2222 3337", "3337"],
    },
    {
        "id": "S17_kimlik_seri_no",
        "kategori": "sizinti",
        "belgeler": {
            "seri.md": "Kimlik Seri No: A12B34567, yeni seri no C09K87654.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[SERİ_NO_1]", "[SERİ_NO_2]"],
        "olmamali": ["A12B34567", "C09K87654"],
    },
    {
        "id": "S18_kimlik_mrz",
        "kategori": "sizinti",
        "belgeler": {
            "mrz.md": (
                "I<TURA12B34567<12345678901<<<<\n"
                "8501015M3001018TUR<<<<<<<<<<<4\n"
                "KAYA<<MEHMET<<<<<<<<<<<<<<<<<<\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[MRZ_1]"],
        "olmamali": ["I<TURA12B34567", "8501015M3001018TUR", "KAYA<<MEHMET"],
    },
    {
        "id": "S19_sicil_hakim_savci_baro",
        "kategori": "sizinti",
        "belgeler": {
            "01_tutanak.md": "T.C. ANKARA 1. HUKUK MAHKEMESİ\nHÂKİM : Mehmet Kaya (112233)\nZABIT KÂTİBİ : Seda Ak (223344)\n",
            "02_imza.md": "Sicil No 112233 ve 223344 tarafından onandı.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[SİCİL_1]", "[SİCİL_2]", "[HAKİM_1]", "[KÂTİP_1]"],
        "olmamali": ["112233", "223344", "Mehmet Kaya", "Seda Ak"],
    },
    {
        "id": "S20_baro_tbb_sicil",
        "kategori": "sizinti",
        "belgeler": {
            "baro.md": "Vekili Av. Kemal Öz (Baro Sicil No: 45678, TBB Sicil: 98765).\n",
        },
        "mod": "varsayilan",
        "olmali": ["Av. Kemal Öz", "[SİCİL_1]", "[SİCİL_2]"],
        "olmamali": ["45678", "98765"],
    },
    {
        "id": "S21_davaci_davali_capraz_belgeler",
        "kategori": "sizinti",
        "belgeler": {
            "01_dava.md": "DAVACI : Ahmet Çelik\nDAVALI : Zeynep Arslan\n",
            "02_cevap.md": "Ahmet Çelik ile Zeynep Arslan arasındaki ihtilafta A. Çelik iddiası.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[DAVALI_1]"],
        "olmamali": ["Ahmet Çelik", "Zeynep Arslan", "A. Çelik"],
    },
    {
        "id": "S22_tanik_musteki_varsayilan_mod",
        "kategori": "sizinti",
        "belgeler": {
            "ifade.md": "TANIK : Murat Kılıç\nMÜŞTEKİ : Selin Yıldız\nMüşteki Selin Yıldız ve tanık Murat Kılıç dinlendi.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[TANIK_1]", "[MÜŞTEKİ_1]"],
        "olmamali": ["Murat Kılıç", "Selin Yıldız"],
    },
    {
        "id": "S23_uc_kelime_ve_soyad_basta",
        "kategori": "sizinti",
        "belgeler": {
            "soyad_on.md": "DAVALI : Fatma Zehra Korkmaz\nKORKMAZ Fatma Zehra beyanda bulundu.\n",
        },
        "mod": "varsayilan",
        "olmali": ["[DAVALI_1]"],
        "olmamali": ["Fatma Zehra Korkmaz", "KORKMAZ Fatma Zehra"],
    },
    {
        "id": "S24_dosya_adi_taraf_adi_ve_link",
        "kategori": "sizinti",
        "belgeler": {
            "Tanik_Murat_Kilic_Beyan.md": "TANIK : Murat Kılıç\nBeyan metni.\n",
            "INDEX.md": "# Dizin\n- [Tanık Beyanı](Tanik_Murat_Kilic_Beyan.md)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[TANIK_1]"],
        "olmamali": ["Murat Kılıç", "Murat_Kilic"],
        "check_filenames": True,
        "check_index_links": True,
    },
    {
        "id": "S25_karisik_rol_tanik_ve_hakim_muhafazakar",
        "kategori": "sizinti",
        "belgeler": {
            "01_tanik.md": "TANIK : Kemal Kaya\nTanık Kemal Kaya beyanında açıkladı.\nTANIK : Kemal Kaya\n",
            "02_karar.md": "T.C. ANKARA 1. ASLİYE HUKUK MAHKEMESİ\nHÂKİM : Kemal Kaya (123456)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["Kemal Kaya", "[TANIK_", "123456"],
    },
    {
        "id": "S26_coklu_sizinti_kombine_sifir_sizinti",
        "kategori": "sizinti",
        "belgeler": {
            "tam.md": (
                "T.C. İSTANBUL 2. TİCARET MAHKEMESİ\n"
                "DAVACI : Orhan Aktaş (TCKN: " + TC3 + ")\n"
                "VEKİLİ : Av. Kerem Aksoy (Baro Sicil: 54321)\n"
                "HÂKİM : Sibel Kaya (112233)\n"
                "İkamet: Erenköy Mah. Şemsettin Günaltay Cad. No: 12 Kadıköy/İstanbul\n"
                "GSM: 0532 999 88 77, IBAN: " + IBAN3 + "\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[TCKN_1]", "Av. Kerem Aksoy", "[SİCİL_", "[HAKİM_1]", "[ADRES_1]", "[TEL_1]", "[IBAN_1]"],
        "olmamali": ["Orhan Aktaş", TC3, "54321", "Sibel Kaya", "112233", "Erenköy Mah.", "0532 999", IBAN3],
    },

    # =========================================================================
    # KATEGORİ D: MOD SENARYOLARI (~11 senaryo)
    # =========================================================================
    {
        "id": "M01_varsayilan_tam_maske_avukat_acik",
        "kategori": "mod",
        "belgeler": {
            "belge.md": (
                "T.C. ANKARA 1. HUKUK MAHKEMESİ\n"
                "DAVACI : Ahmet Çelik\n"
                "TANIK : Murat Kılıç\n"
                "VEKİLİ : Av. Ayşe Yılmaz\n"
                "BİLİRKİŞİ : Bilirkişi Hasan Boz\n"
                "HÂKİM : Mehmet Kaya (112233)\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[TANIK_1]", "Av. Ayşe Yılmaz", "Hasan Boz", "[HAKİM_1]"],
        "olmamali": ["Ahmet Çelik", "Murat Kılıç", "Mehmet Kaya", "112233"],
    },
    {
        "id": "M02_taraf_isimlerini_koru_api",
        "kategori": "mod",
        "belgeler": {
            "belge.md": (
                "T.C. ANKARA 1. HUKUK MAHKEMESİ\n"
                "DAVACI : Ahmet Çelik\n"
                "TANIK : Murat Kılıç\n"
                "HÂKİM : Mehmet Kaya (112233)\n"
            ),
        },
        "mod": "taraf_acik",
        "olmali": ["Ahmet Çelik", "Murat Kılıç", "[HAKİM_1]"],
        "olmamali": ["[DAVACI_", "[TANIK_", "Mehmet Kaya", "112233"],
    },
    {
        "id": "M03_yargi_isimlerini_koru_api",
        "kategori": "mod",
        "belgeler": {
            "belge.md": (
                "T.C. ANKARA 1. HUKUK MAHKEMESİ\n"
                "DAVACI : Ahmet Çelik\n"
                "HÂKİM : Mehmet Kaya (112233)\n"
            ),
        },
        "mod": "yargi_acik",
        "olmali": ["[DAVACI_1]", "Mehmet Kaya", "[SİCİL_1]"],
        "olmamali": ["Ahmet Çelik", "[HAKİM_", "112233"],
        "run_audit": False,  # Yargı adları bilerek açık bırakıldı
    },
    {
        "id": "M04_tum_adlar_acik_api",
        "kategori": "mod",
        "belgeler": {
            "belge.md": (
                "T.C. ANKARA 1. HUKUK MAHKEMESİ\n"
                "DAVACI : Ahmet Çelik (TCKN: " + TC1 + ")\n"
                "HÂKİM : Mehmet Kaya (112233)\n"
            ),
        },
        "mod": "tum_acik",
        "olmali": ["Ahmet Çelik", "Mehmet Kaya", "[TCKN_1]", "[SİCİL_1]"],
        "olmamali": ["[DAVACI_", "[HAKİM_", TC1, "112233"],
        "run_audit": False,
    },
    {
        "id": "M05_cli_klasor_varsayilan_ve_audit",
        "kategori": "mod",
        "belgeler": {
            "belge.md": "T.C. ANKARA 1. HUKUK MAHKEMESİ\nDAVACI : Ahmet Çelik\nHÂKİM : Mehmet Kaya (112233)\nTCKN: " + TC1 + "\n",
        },
        "mod": "cli_folder_default",
        "olmali": ["[DAVACI_1]", "[HAKİM_1]", "[TCKN_1]"],
        "olmamali": ["Ahmet Çelik", "Mehmet Kaya", TC1],
    },
    {
        "id": "M06_cli_klasor_taraf_isimlerini_koru_ve_audit",
        "kategori": "mod",
        "belgeler": {
            "belge.md": "T.C. ANKARA 1. HUKUK MAHKEMESİ\nDAVACI : Ahmet Çelik\nHÂKİM : Mehmet Kaya (112233)\nTCKN: " + TC1 + "\n",
        },
        "mod": "cli_folder_taraf_koru",
        "olmali": ["Ahmet Çelik", "[HAKİM_1]", "[TCKN_1]"],
        "olmamali": ["[DAVACI_", "Mehmet Kaya", TC1],
        "run_audit": False,  # audit_output CLI'da --taraf-isimleri-acik ile yukarıda doğrulandı
    },
    {
        "id": "M07_cli_tek_dosya_iki_mod",
        "kategori": "mod",
        "belgeler": {
            "tek.md": "T.C. ANKARA 1. HUKUK MAHKEMESİ\nDAVACI : Ahmet Çelik\nHÂKİM : Mehmet Kaya (112233)\n",
        },
        "mod": "cli_single_file_both",
        "olmali": ["[DAVACI_1]", "[HAKİM_1]"],
        "olmamali": [],
        "run_audit": False,
    },
    {
        "id": "M08_cli_in_place_her_iki_mod",
        "kategori": "mod",
        "belgeler": {
            "dilekce.md": "T.C. ANKARA 1. HUKUK MAHKEMESİ\nDAVACI : Ahmet Çelik\nHÂKİM : Mehmet Kaya (112233)\n",
        },
        "mod": "cli_in_place_both",
        "olmali": ["[DAVACI_1]", "[HAKİM_1]"],
        "olmamali": [],
        "run_audit": False,
    },
    {
        "id": "M09_cli_geriye_uyumlu_isimleri_koru_ve_maskele_noop",
        "kategori": "mod",
        "belgeler": {
            "dava.md": "T.C. ANKARA 1. HUKUK MAHKEMESİ\nDAVACI : Ahmet Çelik\nHÂKİM : Mehmet Kaya (112233)\n",
        },
        "mod": "cli_legacy_flags",
        "olmali": ["[DAVACI_1]", "[HAKİM_1]"],
        "olmamali": [],
        "run_audit": False,
    },
    {
        "id": "M10_audit_bayraklari_varsayilan_ve_acik",
        "kategori": "mod",
        "belgeler": {
            "dava.md": "T.C. ANKARA 1. HUKUK MAHKEMESİ\nDAVACI : Ahmet Çelik\nHÂKİM : Mehmet Kaya (112233)\n",
        },
        "mod": "audit_flags_matrix",
        "olmali": [],
        "olmamali": [],
        "run_audit": False,
    },
    {
        "id": "M11_karisik_rol_taraf_isimlerini_koru_modunda",
        "kategori": "mod",
        "belgeler": {
            "01_tanik.md": "TANIK : Kemal Kaya\nTanık Kemal Kaya dinlendi.\nTANIK : Kemal Kaya\n",
            "02_karar.md": "T.C. İZMİR 1. HUKUK MAHKEMESİ\nHÂKİM : Kemal Kaya (112233)\n",
        },
        "mod": "taraf_acik",
        "olmali": ["[HAKİM_1]"],
        "olmamali": ["Kemal Kaya", "[TANIK_", "112233"],
    },

    # =========================================================================
    # KATEGORİ E: BİÇİM / KENAR (~11 senaryo)
    # =========================================================================
    {
        "id": "E01_bos_md_dosyasi",
        "kategori": "bicim_kenar",
        "belgeler": {"bos.md": ""},
        "mod": "varsayilan",
        "olmali": [],
        "olmamali": ["[TCKN_", "[KİŞİ_"],
    },
    {
        "id": "E02_cok_buyuk_tek_satir",
        "kategori": "bicim_kenar",
        "belgeler": {
            "dev_satir.md": (
                "T.C. ANKARA 1. TİCARET MAHKEMESİ\n"
                + ("Örnek sözleşme hükmü ve açıklama metni. " * 450)
                + f" HÂKİM : Mehmet Kaya (112233) TCKN: {TC4} IBAN: {IBAN1}"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[TCKN_1]", "[IBAN_1]"],
        "olmamali": ["Mehmet Kaya", TC4, IBAN1, "112233"],
    },
    {
        "id": "E03_unicode_nbsp_ve_nfd_metin",
        "kategori": "bicim_kenar",
        "belgeler": {
            "unicode.md": (
                "T.C. İSTANBUL 1. HUKUK MAHKEMESİ\n"
                "DAVACI\u00a0:\u00a0İğneci\u00a0Şükran\n"
                f"TCKN:\u00a0{TC1}\n"
                "HÂKİM\u00a0:\u00a0Ayşe\u00a0Demir\u00a0(112233)\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[TCKN_1]", "[HAKİM_1]"],
        "olmamali": ["İğneci Şükran", TC1, "Ayşe Demir", "112233"],
    },
    {
        "id": "E04_crlf_satir_sonlari",
        "kategori": "bicim_kenar",
        "belgeler": {
            "crlf.md": (
                "T.C. İZMİR 2. İŞ MAHKEMESİ\r\n"
                "DAVACI : Ahmet Çelik\r\n"
                f"TCKN: {TC2}\r\n"
                "HÂKİM : Mehmet Kaya (112233)\r\n"
                "İkametgah Adresi: Alsancak Mah. Kıbrıs Şehitleri Cad. No: 5 Konak/İzmir\r\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[TCKN_1]", "[HAKİM_1]", "[ADRES_1]"],
        "olmamali": ["Ahmet Çelik", TC2, "Mehmet Kaya", "Alsancak Mah."],
    },
    {
        "id": "E05_markdown_tablo_dikey_ve_sayilar",
        "kategori": "bicim_kenar",
        "belgeler": {
            "tablo_karisik.md": (
                "T.C. ANKARA 4. TİCARET MAHKEMESİ\n"
                "| DAVACI | TCKN | TUTAR |\n"
                "| --- | --- | --- |\n"
                f"| Nevin Şen | {TC1} | 15.000,00 TL |\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[TCKN_1]", "15.000,00 TL"],
        "olmamali": ["Nevin Şen", TC1],
    },
    {
        "id": "E06_satir_sonu_bolunmus_ad",
        "kategori": "bicim_kenar",
        "belgeler": {
            "bolunmus_ad.md": (
                "T.C. BURSA 1. HUKUK MAHKEMESİ\n"
                "BORÇLU : Hakan\n"
                "Yıldırım\n"
                "HÂKİM : Ayşe\n"
                "Demir\n"
                "Hakan Yıldırım ve Ayşe Demir kayda geçti.\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[BORÇLU_1]", "[HAKİM_1]"],
        "olmamali": ["Hakan Yıldırım", "Ayşe Demir"],
    },
    {
        "id": "E07_duz_txt_dosyasi",
        "kategori": "bicim_kenar",
        "belgeler": {
            "not.txt": (
                "T.C. KONYA 1. CEZA MAHKEMESİ\n"
                "TANIK : Caner Başaran\n"
                "HÂKİM : Orhan Çetin (445566)\n"
                f"GSM: 0532 777 66 55 TCKN: {TC1}\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[TANIK_1]", "[HAKİM_1]", "[TEL_1]", "[TCKN_1]"],
        "olmamali": ["Caner Başaran", "Orhan Çetin", "0532 777", TC1, "445566"],
    },
    {
        "id": "E08_sentetik_udf_belgesi",
        "kategori": "bicim_kenar",
        "belgeler": {
            "karar.udf": {
                "__type__": "udf",
                "text": (
                    "T.C. ANKARA 2. ASLİYE HUKUK MAHKEMESİ\n"
                    f"DAVACI : Nihal Sezer ({TC1})\n"
                    "HÂKİM : Nermin Güler (112233)\n"
                    "Yukarıdaki uyuşmazlık hakkında karar verildi."
                ),
            },
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[TCKN_1]", "[HAKİM_1]", "[SİCİL_1]"],
        "olmamali": ["Nihal Sezer", TC1, "Nermin Güler", "112233"],
        "no_ext": (".udf",),
    },
    {
        "id": "E09_sentetik_docx_ve_eyp_arsiv",
        "kategori": "bicim_kenar",
        "belgeler": {
            "paket.eyp": {
                "__type__": "eyp",
                "entries": {
                    "UstYazi/ust.udf": {
                        "__type__": "udf",
                        "text": "T.C. İSTANBUL 1. TİCARET MAHKEMESİ\nHÂKİM : Kemal Demir (112233)\nÜst yazı metni yeterince uzundur.",
                    },
                    "Ekler/ek1.docx": {
                        "__type__": "docx",
                        "paragraphs": [
                            "EK-1 BEYAN",
                            f"DAVACI : Ahmet Çelik (TCKN: {TC1})",
                            "İletişim: 0532 333 44 55 — İşbu ek belge yeterli uzunluktadır.",
                        ],
                    },
                },
            },
        },
        "mod": "varsayilan",
        "olmali": ["[HAKİM_1]", "[DAVACI_1]", "[TCKN_1]", "[TEL_1]"],
        "olmamali": ["Kemal Demir", "Ahmet Çelik", TC1, "0532 333", "112233"],
        "no_ext": (".eyp", ".udf", ".docx"),
    },
    {
        "id": "E10_index_md_link_senkronu",
        "kategori": "bicim_kenar",
        "belgeler": {
            "Ahmet_Celik_Dilekce.md": "DAVACI : Ahmet Çelik\nHÂKİM : Mehmet Kaya (112233)\n",
            "Hakim_Mehmet_Kaya_Karar.md": "T.C. İZMİR 1. HUKUK MAHKEMESİ\nHÂKİM : Mehmet Kaya (112233)\n",
            "INDEX.md": "# Dizin\n- [Dilekçe](Ahmet_Celik_Dilekce.md)\n- [Karar](Hakim_Mehmet_Kaya_Karar.md)\n",
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[HAKİM_1]"],
        "olmamali": ["Ahmet_Celik", "Mehmet_Kaya"],
        "check_index_links": True,
    },
    {
        "id": "E11_rapor_dosyasinda_ham_pii_yok",
        "kategori": "bicim_kenar",
        "belgeler": {
            "dava.md": (
                "T.C. ANKARA 3. İŞ MAHKEMESİ\n"
                "DAVACI : Ahmet Çelik\n"
                "HÂKİM : Mehmet Kaya (112233)\n"
                f"TCKN: {TC1}\nGSM: 0532 888 99 00\nIBAN: {IBAN1}\n"
                "İkametgah Adresi: Yıldız Mah. 10. Sok. No:5 Çankaya/Ankara\n"
            ),
        },
        "mod": "varsayilan",
        "olmali": ["[DAVACI_1]", "[HAKİM_1]", "[TCKN_1]", "[TEL_1]", "[IBAN_1]", "[ADRES_1]"],
        "olmamali": ["Ahmet Çelik", "Mehmet Kaya", TC1, "0532 888", IBAN1, "Yıldız Mah."],
        "check_report_clean": ["Ahmet Çelik", "Mehmet Kaya", TC1, "0532 888", IBAN1, "Yıldız Mah.", "112233"],
    },
]


def _run_scenario(test_obj: unittest.TestCase, sen: Dict[str, Any]) -> None:
    mod = sen["mod"]
    with tempfile.TemporaryDirectory(prefix=f"uyap_100_{sen['id']}_") as tmp:
        src = os.path.join(tmp, "src")
        dest = os.path.join(tmp, "out")
        os.makedirs(src, exist_ok=True)
        _materialize_tree(src, sen["belgeler"])

        # Özel CLI ve audit matrisi senaryoları
        if mod == "cli_folder_default":
            with patch.object(sys, "argv", ["uyap_redactor.py", src, "--out", dest]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            res = A.audit(src, dest)
            test_obj.assertEqual(res["leaks"]["person_name"], [])
            test_obj.assertFalse(A.summarize(res)[2])
            test_obj.assertEqual(A.main([src, dest]), 0)
            out_dir = dest
        elif mod == "cli_folder_taraf_koru":
            with patch.object(sys, "argv", ["uyap_redactor.py", src, "--out", dest, "--taraf-isimlerini-koru"]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            res = A.audit(src, dest, mask_names=False)
            test_obj.assertEqual(res["leaks"]["person_name"], [])
            test_obj.assertFalse(A.summarize(res)[2])
            test_obj.assertEqual(A.main([src, dest, "--taraf-isimleri-acik"]), 0)
            out_dir = dest
        elif mod == "cli_single_file_both":
            single_md = os.path.join(src, "tek.md")
            with patch.object(sys, "argv", ["uyap_redactor.py", single_md, "--out", dest]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            txt_def = open(os.path.join(dest, "tek.md"), encoding="utf-8").read()
            test_obj.assertIn("[DAVACI_1]", txt_def)
            test_obj.assertIn("[HAKİM_1]", txt_def)
            test_obj.assertNotIn("Ahmet Çelik", txt_def)
            test_obj.assertNotIn("Mehmet Kaya", txt_def)

            dest_koru = os.path.join(tmp, "out_koru")
            with patch.object(sys, "argv", ["uyap_redactor.py", single_md, "--out", dest_koru, "--taraf-isimlerini-koru"]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            txt_koru = open(os.path.join(dest_koru, "tek.md"), encoding="utf-8").read()
            test_obj.assertIn("Ahmet Çelik", txt_koru)
            test_obj.assertIn("[HAKİM_1]", txt_koru)
            test_obj.assertNotIn("Mehmet Kaya", txt_koru)
            out_dir = dest
        elif mod == "cli_in_place_both":
            def_dir = os.path.join(tmp, "ip_def")
            os.makedirs(def_dir, exist_ok=True)
            _materialize_tree(def_dir, sen["belgeler"])
            with patch.object(sys, "argv", ["uyap_redactor.py", def_dir, "--in-place"]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            ip_def_txt = open(os.path.join(def_dir, "dilekce.md"), encoding="utf-8").read()
            test_obj.assertIn("[DAVACI_1]", ip_def_txt)
            test_obj.assertIn("[HAKİM_1]", ip_def_txt)
            test_obj.assertNotIn("Ahmet Çelik", ip_def_txt)
            test_obj.assertNotIn("Mehmet Kaya", ip_def_txt)

            open_dir = os.path.join(tmp, "ip_open")
            os.makedirs(open_dir, exist_ok=True)
            _materialize_tree(open_dir, sen["belgeler"])
            with patch.object(sys, "argv", ["uyap_redactor.py", open_dir, "--in-place", "--taraf-isimlerini-koru"]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            ip_open_txt = open(os.path.join(open_dir, "dilekce.md"), encoding="utf-8").read()
            test_obj.assertIn("Ahmet Çelik", ip_open_txt)
            test_obj.assertIn("[HAKİM_1]", ip_open_txt)
            test_obj.assertNotIn("Mehmet Kaya", ip_open_txt)

            jud_dir = os.path.join(tmp, "ip_jud_open")
            os.makedirs(jud_dir, exist_ok=True)
            _materialize_tree(jud_dir, sen["belgeler"])
            with patch.object(sys, "argv", ["uyap_redactor.py", jud_dir, "--in-place", "--yargi-isimlerini-koru"]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            ip_jud_txt = open(os.path.join(jud_dir, "dilekce.md"), encoding="utf-8").read()
            test_obj.assertIn("[DAVACI_1]", ip_jud_txt)
            test_obj.assertIn("Mehmet Kaya", ip_jud_txt)
            test_obj.assertNotIn("Ahmet Çelik", ip_jud_txt)
            out_dir = def_dir
        elif mod == "cli_legacy_flags":
            dest_old_k = os.path.join(tmp, "out_old_koru")
            with patch.object(sys, "argv", ["uyap_redactor.py", src, "--out", dest_old_k, "--isimleri-koru"]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            txt_old_k = open(os.path.join(dest_old_k, "dava.md"), encoding="utf-8").read()
            test_obj.assertIn("Ahmet Çelik", txt_old_k)
            test_obj.assertIn("[HAKİM_1]", txt_old_k)
            test_obj.assertNotIn("Mehmet Kaya", txt_old_k)

            with patch.object(sys, "argv", ["uyap_redactor.py", src, "--out", dest, "--taraf-isimlerini-maskele"]):
                with redirect_stdout(io.StringIO()):
                    R.main()
            txt_noop = open(os.path.join(dest, "dava.md"), encoding="utf-8").read()
            test_obj.assertIn("[DAVACI_1]", txt_noop)
            test_obj.assertIn("[HAKİM_1]", txt_noop)
            test_obj.assertNotIn("Ahmet Çelik", txt_noop)
            test_obj.assertNotIn("Mehmet Kaya", txt_noop)
            out_dir = dest
        elif mod == "audit_flags_matrix":
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest, mask_names=False)
            # Taraf adı açıkken varsayılan audit ve etkisiz --taraf-isimleri çıkış kodu 1 olmalı
            test_obj.assertEqual(A.main([src, out_dir]), 1)
            test_obj.assertEqual(A.main([src, out_dir, "--taraf-isimleri"]), 1)
            # --taraf-isimleri-acik ile 0 olmalı
            test_obj.assertEqual(A.main([src, out_dir, "--taraf-isimleri-acik"]), 0)
            return
        else:
            mode_kwargs = {
                "varsayilan": {},
                "taraf_acik": {"mask_names": False},
                "yargi_acik": {"mask_judicial_names": False},
                "tum_acik": {"mask_names": False, "mask_judicial_names": False},
            }[mod]
            out_dir, _ = UyapRedactor.export_isolated_clean_folder(src, dest, **mode_kwargs)

        doc_texts, all_texts = _read_all_outputs(out_dir)
        combined = "\n".join(doc_texts.values())

        for must in sen["olmali"]:
            test_obj.assertIn(must, combined, f"[{sen['id']}] beklenen bulunamadı: {must}\n--- Çıktı ---\n{combined}")

        for must_not in sen["olmamali"]:
            test_obj.assertNotIn(must_not, combined, f"[{sen['id']}] yasaklı ham değer kaldı: {must_not}\n--- Çıktı ---\n{combined}")

        if sen.get("check_filenames"):
            rels = list(doc_texts.keys())
            for must_not in sen["olmamali"]:
                for rel in rels:
                    test_obj.assertNotIn(must_not, rel, f"[{sen['id']}] dosya adında sızıntı: {rel}")

        if sen.get("check_index_links"):
            idx_txt = all_texts.get("INDEX.md", "")
            for must_not in sen["olmamali"]:
                test_obj.assertNotIn(must_not, idx_txt, f"[{sen['id']}] INDEX.md içinde sızıntı: {must_not}")
            links = re.findall(r'\]\((?:<([^>\n]+)>|([^)\s]+))\)', idx_txt)
            links = [a or b for a, b in links]
            test_obj.assertTrue(len(links) >= 1, f"[{sen['id']}] INDEX.md bağlantısı boş")
            for lnk in links:
                target = unquote(lnk.strip())
                test_obj.assertTrue(
                    os.path.exists(os.path.join(out_dir, target)),
                    f"[{sen['id']}] kırık INDEX bağlantısı: {target}",
                )

        if sen.get("no_ext"):
            bad_exts = tuple(sen["no_ext"])
            for _r, _d, files in os.walk(out_dir):
                for fn in files:
                    test_obj.assertFalse(fn.lower().endswith(bad_exts), f"[{sen['id']}] ham dosya kaldı: {fn}")

        if sen.get("check_report_clean"):
            rapor = all_texts.get(UyapRedactor.REPORT_NAME, "")
            test_obj.assertIn("hiçbir yere yazılmadı", rapor)
            for forbidden in sen["check_report_clean"]:
                test_obj.assertNotIn(forbidden, rapor, f"[{sen['id']}] raporda ham değer: {forbidden}")

        if sen.get("run_audit", True):
            audit_mask_names = mod != "taraf_acik"
            res = A.audit(src, out_dir, mask_names=audit_mask_names)
            test_obj.assertEqual(
                res["leaks"]["person_name"],
                [],
                f"[{sen['id']}] audit person_name sızıntısı: {res['leaks']['person_name']}",
            )
            test_obj.assertFalse(
                A.summarize(res)[2],
                f"[{sen['id']}] audit sızıntı bildirdi: {res['leaks']}",
            )


class TestYuzSenaryo(unittest.TestCase):
    """100+ dinamik üretilen senaryo testi (her senaryo ayrı test metodu)."""

    ALARM_SECONDS = 30

    def setUp(self) -> None:
        self._prev_handler = signal.getsignal(signal.SIGALRM)

        def _alarm_handler(signum, frame):
            raise TimeoutError(f"Senaryo testi zaman aşımı (>{self.ALARM_SECONDS}s)")

        signal.signal(signal.SIGALRM, _alarm_handler)
        signal.alarm(self.ALARM_SECONDS)

    def tearDown(self) -> None:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self._prev_handler)


def _register_scenario_tests() -> None:
    seen_ids = set()
    for sen in SENARYOLAR:
        sid = sen["id"]
        assert sid not in seen_ids, f"Yinelenen senaryo id: {sid}"
        seen_ids.add(sid)

        def _make_method(scenario: Dict[str, Any]) -> Callable[[unittest.TestCase], None]:
            def _test(self: unittest.TestCase) -> None:
                _run_scenario(self, scenario)
            _test.__doc__ = f"[{scenario['kategori']}] {scenario['id']}"
            return _test

        setattr(TestYuzSenaryo, f"test_{sid}", _make_method(sen))


_register_scenario_tests()


if __name__ == "__main__":
    unittest.main()
