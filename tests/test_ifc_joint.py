"""解析フェーズ (ifc.joint) のテスト。

受ける材の判定(端点が相手材の footprint に入るか・平行/レイヤ/Z 範囲の
除外)は合成入力で、命令組み立ては実 IFC フィクスチャで検証する。
いずれも vs 非依存。
"""
from __future__ import annotations

import math
import os

import ifcopenshell

from vectorworks_plugin_import_ifc_homeskz.document import MemberCommand
from vectorworks_plugin_import_ifc_homeskz.ifc import joint, open_ifc

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


def _open(filename: str) -> ifcopenshell.file:
    return open_ifc(os.path.join(FIXTURES_DIR, filename))


def _member(
    layer: str,
    start: tuple[float, float],
    end: tuple[float, float],
    width: float = 120.0,
    height: float = 180.0,
    elevation: float = 425.0,
    end_elevation: float = 425.0,
) -> MemberCommand:
    return {
        'layer': layer,
        'member_id': 'x',
        'class': '04構造-02木造-01土台-01土台',
        'start': [start[0], start[1]],
        'end': [end[0], end[1]],
        'width': width,
        'height': height,
        'elevation': elevation,
        'end_elevation': end_elevation,
        'start_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
        'end_bound': {'story_offset': 0, 'level': '横架材天端', 'offset': 0.0},
    }


class TestPointInMember:
    # 中心線 x=0..3000・y=0、半幅 60 の材(相手)
    OTHER = (0.0, 0.0, 3000.0, 0.0, 1.0, 0.0, 3000.0, 60.0, 245.0, 425.0)

    def test_point_on_top_face_is_inside(self) -> None:
        # 天端面(y=60)ちょうどに載る端点は取り付きとみなす
        assert joint._point_in_member(1500.0, 60.0, self.OTHER)

    def test_point_inside_rectangle(self) -> None:
        assert joint._point_in_member(1500.0, 0.0, self.OTHER)

    def test_point_beyond_face_is_outside(self) -> None:
        # 半幅 + 余裕を超えて離れた端点は取り付かない
        assert not joint._point_in_member(1500.0, 100.0, self.OTHER)

    def test_point_beyond_length_is_outside(self) -> None:
        assert not joint._point_in_member(4000.0, 0.0, self.OTHER)

    def test_point_at_end_corner_is_inside(self) -> None:
        # 相手材の端(コーナー)に載る端点も取り付きとみなす
        assert joint._point_in_member(0.0, 0.0, self.OTHER)


class TestEndHasReceiver:
    def test_t_junction_stem_end_is_received(self) -> None:
        # A=通し材(x 方向)、B=A の側面に突き当たる材(y 方向)。B の始端は
        # A の天端面に載るため受ける材(A)がある。
        a = _member('L', (0.0, 0.0), (3000.0, 0.0))
        b = _member('L', (1500.0, 60.0), (1500.0, 2000.0))
        geoms = [joint._member_geom(a), joint._member_geom(b)]
        members = [a, b]
        assert joint._end_has_receiver(1, 1500.0, 60.0, geoms, members)

    def test_through_member_free_end_is_not_received(self) -> None:
        # A の端点(0,0)/(3000,0)は B に取り付かない(B は A の中間に突き当たる)
        a = _member('L', (0.0, 0.0), (3000.0, 0.0))
        b = _member('L', (1500.0, 60.0), (1500.0, 2000.0))
        geoms = [joint._member_geom(a), joint._member_geom(b)]
        members = [a, b]
        assert not joint._end_has_receiver(0, 0.0, 0.0, geoms, members)
        assert not joint._end_has_receiver(0, 3000.0, 0.0, geoms, members)

    def test_parallel_splice_is_not_received(self) -> None:
        # 同一直線上の継ぎ手(平行)は受ける材にしない
        a = _member('L', (0.0, 0.0), (1000.0, 0.0))
        b = _member('L', (1000.0, 0.0), (2000.0, 0.0))
        geoms = [joint._member_geom(a), joint._member_geom(b)]
        members = [a, b]
        assert not joint._end_has_receiver(0, 1000.0, 0.0, geoms, members)
        assert not joint._end_has_receiver(1, 1000.0, 0.0, geoms, members)

    def test_different_layer_is_not_received(self) -> None:
        a = _member('L1', (0.0, 0.0), (3000.0, 0.0))
        b = _member('L2', (1500.0, 60.0), (1500.0, 2000.0))
        geoms = [joint._member_geom(a), joint._member_geom(b)]
        members = [a, b]
        assert not joint._end_has_receiver(1, 1500.0, 60.0, geoms, members)

    def test_separated_z_is_not_received(self) -> None:
        # 段差で Z 範囲が離れた相手は受ける材にしない
        a = _member('L', (0.0, 0.0), (3000.0, 0.0), elevation=425.0,
                    end_elevation=425.0)
        b = _member('L', (1500.0, 60.0), (1500.0, 2000.0),
                    elevation=2000.0, end_elevation=2000.0)
        geoms = [joint._member_geom(a), joint._member_geom(b)]
        members = [a, b]
        assert not joint._end_has_receiver(1, 1500.0, 60.0, geoms, members)


class TestDegenerateMembers:
    def test_member_geom_returns_none_for_zero_length(self) -> None:
        # 始端 = 終端(平面投影長 0)の材はジオメトリが定まらず None
        degenerate = _member('1-横架材天端', (500.0, 500.0), (500.0, 500.0))
        assert joint._member_geom(degenerate) is None

    def test_end_has_receiver_false_when_own_geom_none(self) -> None:
        # 判定対象の材が退化(geom None)なら受ける材は無いものとして False
        degenerate = _member('1-横架材天端', (500.0, 500.0), (500.0, 500.0))
        other = _member('1-横架材天端', (0.0, 0.0), (3000.0, 0.0))
        geoms = [joint._member_geom(degenerate), joint._member_geom(other)]
        members = [degenerate, other]
        assert not joint._end_has_receiver(0, 500.0, 500.0, geoms, members)

    def test_build_skips_degenerate_member(self) -> None:
        # 退化した材は端部・向きが定まらないため joint 命令を出さない
        degenerate = _member('1-横架材天端', (0.0, 0.0), (0.0, 0.0))
        other = _member('1-横架材天端', (0.0, 0.0), (3000.0, 0.0))
        assert joint.build_joint_commands([degenerate, other]) == []


class TestBuildJointCommands:
    def test_t_junction_places_single_joint_at_stem_end(self) -> None:
        a = _member('1-横架材天端', (0.0, 0.0), (3000.0, 0.0))
        b = _member('1-横架材天端', (1500.0, 60.0), (1500.0, 2000.0))
        commands = joint.build_joint_commands([a, b])
        assert len(commands) == 1
        cmd = commands[0]
        assert cmd['symbol'] == '仕口'
        assert cmd['layer'] == '1-横架材天端'
        assert cmd['position'] == [1500.0, 60.0]
        # 内側方向(+Y, B の始端から終端へ)= 90 度
        assert math.isclose(cmd['angle'], 90.0)

    def test_free_member_has_no_joints(self) -> None:
        a = _member('1-横架材天端', (0.0, 0.0), (3000.0, 0.0))
        assert joint.build_joint_commands([a]) == []

    def test_both_ends_received_places_two_joints(self) -> None:
        # 2 本の桁の間に架かる梁は両端に仕口が付く
        left = _member('1-横架材天端', (0.0, -2000.0), (0.0, 2000.0))
        right = _member('1-横架材天端', (3000.0, -2000.0), (3000.0, 2000.0))
        span = _member('1-横架材天端', (60.0, 0.0), (2940.0, 0.0))
        commands = joint.build_joint_commands([left, right, span])
        span_joints = [c for c in commands
                       if c['position'] in ([60.0, 0.0], [2940.0, 0.0])]
        assert len(span_joints) == 2

    def test_result_is_order_independent(self) -> None:
        a = _member('1-横架材天端', (0.0, 0.0), (3000.0, 0.0))
        b = _member('1-横架材天端', (1500.0, 60.0), (1500.0, 2000.0))
        c = _member('1-横架材天端', (5000.0, 5000.0), (7000.0, 5000.0))
        s1 = sorted(tuple(x['position'])
                    for x in joint.build_joint_commands([a, b, c]))
        s2 = sorted(tuple(x['position'])
                    for x in joint.build_joint_commands([c, b, a]))
        assert s1 == s2


class TestBuildFromFixture:
    FILENAME = '伏図次郎【2階】.ifc'

    def test_command_shape(self) -> None:
        from vectorworks_plugin_import_ifc_homeskz.ifc import (
            build_member_commands,
        )
        ifc = _open(self.FILENAME)
        members = build_member_commands(ifc)
        joints = joint.build_joint_commands(members)
        assert joints
        member_layers = {m['layer'] for m in members}
        for j in joints:
            assert j['symbol'] == '仕口'
            # 仕口は横架材と同じレイヤに置く
            assert j['layer'] in member_layers
            assert len(j['position']) == 2
            assert isinstance(j['angle'], float)

    def test_positions_are_centered(self) -> None:
        from vectorworks_plugin_import_ifc_homeskz.ifc import (
            build_member_commands,
        )
        ifc = _open(self.FILENAME)
        joints = joint.build_joint_commands(build_member_commands(ifc))
        xs = [j['position'][0] for j in joints]
        ys = [j['position'][1] for j in joints]
        assert min(xs) < 0 < max(xs)
        assert min(ys) < 0 < max(ys)

    def test_all_fixtures_build_without_error(self) -> None:
        from vectorworks_plugin_import_ifc_homeskz.ifc import (
            build_member_commands,
        )
        for filename in (
            'サンプル1 (住木邸新築工事).ifc',
            'スキップフロア_サンプル.ifc',
            'グレー本モデルプラン1【3階】.ifc',
            'グレー本モデルプラン2【3階】.ifc',
        ):
            ifc = _open(filename)
            joints = joint.build_joint_commands(build_member_commands(ifc))
            assert joints
            for j in joints:
                assert j['symbol'] == '仕口'
