"""Spec 053 (U12): tokens that must stay Latin in Cyrillic text, and EU -> ЕУ."""
from smartagri.translit import to_cyrillic


def test_protected_tokens_stay_latin():
    assert to_cyrillic("Push obaveštenja") == "Push обавештења"
    assert to_cyrillic("Vremenska zona, npr. Europe/Belgrade").endswith("Europe/Belgrade")
    assert to_cyrillic("Copernicus Data Space Ecosystem") == "Copernicus Data Space Ecosystem"
    assert to_cyrillic("Uvezi iz Google Earth") == "Увези из Google Earth"


def test_eu_is_written_in_cyrillic():
    assert to_cyrillic("prema Uredbi EU 2023/1115") == "према Уредби ЕУ 2023/1115"
    assert "EUDR" in to_cyrillic("izjava EUDR")
