"""構造クラス判定 (ifc.structural_class) のテスト。vs 非依存・純関数。"""
from __future__ import annotations

from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
    CLASS_DODAI,
    CLASS_KOYABARI,
    CLASS_KOYAZUKA,
    CLASS_KUDABASHIRA,
    CLASS_MOYA,
    CLASS_TOSHIBASHIRA,
    CLASS_YUKABARI,
    member_class_from_name,
    member_type_of_name,
    resolve_column_class,
    resolve_member_class,
)


class TestMemberTypeOfName:
    def test_wood_beam_uses_middle_token(self) -> None:
        assert member_type_of_name('木梁:土台:1') == '土台'
        assert member_type_of_name('木梁:軒桁:1_1_0') == '軒桁'
        assert member_type_of_name('木梁:床大梁:1_5') == '床大梁'

    def test_two_part_name_uses_prefix(self) -> None:
        assert member_type_of_name('火打:0_1') == '火打'
        assert member_type_of_name('筋かい:1FL_1') == '筋かい'

    def test_handles_none_and_empty(self) -> None:
        assert member_type_of_name(None) == ''
        assert member_type_of_name('') == ''


class TestMemberClassFromName:
    def test_known_types_map_directly(self) -> None:
        assert member_class_from_name('木梁:土台:1') == CLASS_DODAI
        # 床小梁・床大梁・甲乙梁はいずれも床梁にまとめる
        assert member_class_from_name('木梁:床小梁:1') == CLASS_YUKABARI
        assert member_class_from_name('木梁:床大梁:1') == CLASS_YUKABARI
        assert member_class_from_name('木梁:甲乙梁:1') == CLASS_YUKABARI
        assert member_class_from_name('木梁:母屋:1') == CLASS_MOYA

    def test_unknown_types_return_none(self) -> None:
        assert member_class_from_name('木梁:隅木・谷木:1') is None
        assert member_class_from_name('火打:0_1') is None
        assert member_class_from_name(None) is None


class TestResolveMemberClass:
    def test_name_is_trusted_over_position(self) -> None:
        # 名前で判別できれば階・高さに依らずその種別クラスにする
        assert resolve_member_class('木梁:小屋梁:1', 0, 2, above_eaves=False) \
            == CLASS_KOYABARI

    def test_fallback_lowest_story_is_dodai(self) -> None:
        assert resolve_member_class(None, 0, 2, above_eaves=False) == CLASS_DODAI

    def test_fallback_middle_story_is_yukabari(self) -> None:
        assert resolve_member_class('火打:1_1', 1, 2, above_eaves=False) \
            == CLASS_YUKABARI

    def test_fallback_top_story_at_eaves_is_koyabari(self) -> None:
        assert resolve_member_class('木梁:隅木・谷木:1', 2, 2, above_eaves=False) \
            == CLASS_KOYABARI

    def test_fallback_top_story_above_eaves_is_moya(self) -> None:
        assert resolve_member_class('木梁:隅木・谷木:1', 2, 2, above_eaves=True) \
            == CLASS_MOYA


class TestResolveColumnClass:
    def test_standcolumn_object_type_is_koyazuka(self) -> None:
        assert resolve_column_class('STANDCOLUMN', '小屋束:1_1', 1, 2, False) \
            == CLASS_KOYAZUKA

    def test_koyazuka_name_without_object_type(self) -> None:
        assert resolve_column_class(None, '小屋束:2_1', 1, 2, False) == CLASS_KOYAZUKA

    def test_top_story_column_falls_back_to_koyazuka(self) -> None:
        assert resolve_column_class(None, '柱:3_1', 2, 2, False) == CLASS_KOYAZUKA

    def test_general_story_short_column_is_kudabashira(self) -> None:
        assert resolve_column_class(None, '柱:1_1', 0, 2, is_through=False) \
            == CLASS_KUDABASHIRA

    def test_general_story_through_column_is_toshibashira(self) -> None:
        assert resolve_column_class(None, '柱:1_1', 0, 2, is_through=True) \
            == CLASS_TOSHIBASHIRA
