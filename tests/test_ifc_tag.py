"""解析フェーズ (ifc.tag) のテスト。横架材から断面寸法データタグ命令を組み立てる。

vs 非依存。手書きの member 命令を入力にタグの位置・角度・関連付けを検証する。
"""
from __future__ import annotations

import math

from vectorworks_plugin_import_ifc_homeskz.document import MemberCommand
from vectorworks_plugin_import_ifc_homeskz.ifc.tag import (
    TAG_STYLE,
    build_tag_commands,
)


def make_member(
    start: tuple[float, float] = (0.0, 0.0),
    end: tuple[float, float] = (3000.0, 0.0),
    width: float = 120.0,
    layer: str = '1-横架材天端',
) -> MemberCommand:
    return {
        'layer': layer,
        'member_id': '120×180 - 杉',
        'class': '04構造-02木造-01土台-01土台',
        'start': list(start),
        'end': list(end),
        'width': width,
        'height': 180.0,
        'elevation': 425.0,
        'end_elevation': 425.0,
        'start_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
        'end_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
    }


class TestBuildTagCommands:
    def test_empty_members_yield_no_tags(self) -> None:
        assert build_tag_commands([]) == []

    def test_one_tag_per_member(self) -> None:
        tags = build_tag_commands([make_member(), make_member()])
        assert len(tags) == 2

    def test_tag_uses_section_style_and_member_layer(self) -> None:
        tags = build_tag_commands([make_member(layer='2-横架材天端')])
        assert tags[0]['style'] == TAG_STYLE
        assert tags[0]['layer'] == '2-横架材天端'

    def test_member_index_references_source_order(self) -> None:
        tags = build_tag_commands([make_member(), make_member(), make_member()])
        assert [t['member_index'] for t in tags] == [0, 1, 2]

    def test_east_west_member_tag_placed_above(self) -> None:
        """東西向き(横)の横架材はタグを上(+Y 側)へ寄せる。"""
        tags = build_tag_commands([
            make_member(start=(0.0, 0.0), end=(2000.0, 0.0), width=120.0),
        ])
        pos = tags[0]['position']
        # 中央 (1000, 0) から上へ 幅/2 + 余白 = 60 + 100 = 160
        assert pos[0] == 1000.0
        assert pos[1] == 160.0
        # 軸方向 (水平) に沿った角度は 0 度
        assert tags[0]['angle'] == 0.0

    def test_north_south_member_tag_placed_left(self) -> None:
        """南北向き(縦)の横架材はタグを左(-X 側)へ寄せる。"""
        tags = build_tag_commands([
            make_member(start=(0.0, 0.0), end=(0.0, 2000.0), width=120.0),
        ])
        pos = tags[0]['position']
        # 中央 (0, 1000) から左へ 幅/2 + 余白 = 160
        assert pos[0] == -160.0
        assert pos[1] == 1000.0
        # 軸方向 (鉛直) に沿った角度は 90 度
        assert tags[0]['angle'] == 90.0

    def test_reversed_east_west_member_still_above(self) -> None:
        """西向き(終点が始点より左)でもタグは上へ寄せ、角度も (-90, 90] に収める。"""
        tags = build_tag_commands([
            make_member(start=(2000.0, 0.0), end=(0.0, 0.0), width=120.0),
        ])
        pos = tags[0]['position']
        assert pos[0] == 1000.0
        assert pos[1] == 160.0
        assert tags[0]['angle'] == 0.0

    def test_reversed_north_south_member_still_left(self) -> None:
        """南向き(終点が始点より下)でもタグは左へ寄せる。"""
        tags = build_tag_commands([
            make_member(start=(0.0, 2000.0), end=(0.0, 0.0), width=120.0),
        ])
        pos = tags[0]['position']
        assert pos[0] == -160.0
        assert pos[1] == 1000.0
        assert tags[0]['angle'] == 90.0

    def test_diagonal_member_angle_follows_axis(self) -> None:
        """斜めの横架材(登り梁等)の角度は軸方向に沿う。"""
        tags = build_tag_commands([
            make_member(start=(0.0, 0.0), end=(1000.0, 1000.0), width=120.0),
        ])
        assert tags[0]['angle'] == 45.0
        # 上寄りの直交方向(左上)へオフセットされる
        cx, cy = 500.0, 500.0
        assert tags[0]['position'][0] < cx
        assert tags[0]['position'][1] > cy

    def test_offset_scales_with_member_width(self) -> None:
        """オフセット量は断面幅に応じて変わる(幅/2 + 一定余白)。"""
        narrow = build_tag_commands([make_member(width=100.0)])[0]
        wide = build_tag_commands([make_member(width=300.0)])[0]
        # 幅 300 の方が 100 mm 分だけ上に離れる ((300-100)/2 = 100)
        assert wide['position'][1] - narrow['position'][1] == 100.0

    def test_zero_length_member_uses_default_upward_offset(self) -> None:
        """始点と終点が同じ(長さ 0)の材でも既定(上)方向へオフセットして落ちない。"""
        tags = build_tag_commands([
            make_member(start=(100.0, 200.0), end=(100.0, 200.0), width=120.0),
        ])
        # 向きを決められないため既定の上方向 (0, 1) へ 幅/2 + 余白 = 160
        assert tags[0]['position'] == [100.0, 360.0]

    def test_offset_direction_is_perpendicular_to_axis(self) -> None:
        """オフセットは軸に直交している。"""
        member = make_member(start=(0.0, 0.0), end=(1000.0, 500.0))
        tag = build_tag_commands([member])[0]
        cx, cy = 500.0, 250.0
        ox, oy = tag['position'][0] - cx, tag['position'][1] - cy
        # オフセットベクトルと軸ベクトルの内積は 0(直交)
        assert math.isclose(ox * 1000.0 + oy * 500.0, 0.0, abs_tol=1e-6)
