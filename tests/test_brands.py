from app.brands import BrandRegistry


def test_all_six_brands_are_registered():
    registry = BrandRegistry()
    assert {b["id"] for b in registry.list_brands()} == {
        "schneider", "abb", "siemens", "danfoss", "invt", "inovance"
    }


def test_model_identification_prefers_longest_family_alias():
    registry = BrandRegistry()
    assert registry.identify("设备铭牌：ATV610HD15N4")["series"] == "ATV610"
    assert registry.identify("ABB ACS880-01")["series"] == "ACS880"
    assert registry.identify("SINAMICS G120C")["series"] == "SINAMICS G120C"
    assert registry.identify("丹佛斯 VLT FC302")["series"] == "VLT FC302"
    assert registry.identify("INVT GD200A")["series"] == "GD200A"
    assert registry.identify("汇川 MD520")["series"] == "MD520"


def test_brand_without_model_does_not_guess_series():
    result = BrandRegistry().identify("ABB 变频器故障")
    assert result == {"brand": "abb", "brand_name": "ABB", "series": ""}
    assert BrandRegistry().identify("过流故障，运行十分钟后跳闸") is None


def test_registry_can_be_loaded_from_json(tmp_path):
    import json
    path = tmp_path / "brands.json"
    path.write_text(json.dumps([{"id": "test", "name": "测试", "aliases": ["TEST"],
                                 "families": [{"id": "T100", "aliases": ["T100"]}]}]), encoding="utf-8")
    assert BrandRegistry.load(path).identify("T100")["brand"] == "test"
