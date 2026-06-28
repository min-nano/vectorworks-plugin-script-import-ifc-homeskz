"""IFC 読み込み・サニタイズ (ifc.loader) のテスト。vs 非依存。"""
from __future__ import annotations

import os

from vectorworks_plugin_import_ifc_homeskz.ifc import loader, open_ifc

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')

_IFC2X3_HEADER = (
    "ISO-10303-21;\n"
    "HEADER;\n"
    "FILE_DESCRIPTION((''),'2;1');\n"
    "FILE_NAME('x','t',(''),(''),'','','');\n"
    "FILE_SCHEMA(('IFC2X3'));\n"
    "ENDSEC;\n"
    "DATA;\n"
)


class TestSanitize:
    def test_strips_invalid_footing_type_in_ifc2x3(self) -> None:
        text = (
            _IFC2X3_HEADER
            + "#1= IFCFOOTING('g',$,'基礎梁:1',$,$,$,$,$,.FOOTING_BEAM.);\n"
            + "#2= IFCFOOTINGTYPE('t',$,'FG1',$,$,$,$,$,$);\n"
            + "ENDSEC;\nEND-ISO-10303-21;\n"
        )
        sanitized = loader._sanitize(text)
        assert sanitized is not None
        assert 'IFCFOOTINGTYPE' not in sanitized
        # 正常な IFCFOOTING は残る
        assert 'IFCFOOTING(' in sanitized

    def test_returns_none_when_no_invalid_entities(self) -> None:
        text = (
            _IFC2X3_HEADER
            + "#1= IFCFOOTING('g',$,'基礎梁:1',$,$,$,$,$,.FOOTING_BEAM.);\n"
            + "ENDSEC;\nEND-ISO-10303-21;\n"
        )
        assert loader._sanitize(text) is None

    def test_returns_none_for_non_ifc2x3(self) -> None:
        text = (
            "ISO-10303-21;\nHEADER;\nFILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n"
            + "#2= IFCFOOTINGTYPE('t',$,'FG1',$,$,$,$,$,$);\n"
            + "ENDSEC;\nEND-ISO-10303-21;\n"
        )
        # IFC4 では IfcFootingType は正当なので触らない
        assert loader._sanitize(text) is None

    def test_instance_regex_matches_only_target(self) -> None:
        line = "#5= IFCFOOTINGTYPE('t',#11,'FG1',$,$,(#6),$,$,$);"
        assert loader._INSTANCE_RE.search(line) is not None
        assert loader._INSTANCE_RE.search("#5= IFCFOOTING('g',$,'x',$,$,$,$,$,$);") is None


class TestOpenIfc:
    def test_loads_all_footings_from_fixture(self) -> None:
        """サニタイズにより古い ifcopenshell でも基礎が取りこぼされない。"""
        ifc = open_ifc(os.path.join(FIXTURES_DIR, '伏図次郎【2階】.ifc'))
        # 不正エンティティで取りこぼすと 1 件しか読めない。サニタイズ後は多数。
        assert len(ifc.by_type('IfcFooting')) > 50

    def test_falls_back_for_missing_file(self) -> None:
        # 読み込めないパスはサニタイズせず ifcopenshell.open に委ね、その例外が出る
        try:
            open_ifc(os.path.join(FIXTURES_DIR, '__does_not_exist__.ifc'))
        except Exception:
            pass
        else:  # pragma: no cover - 例外が出ない場合のみ
            raise AssertionError('存在しないファイルで例外が送出されるはず')
