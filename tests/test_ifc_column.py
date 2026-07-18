"""IFC 解析フェーズ (ifc.column) のテスト。vs に依存せず実 IFC データで検証できる。"""
from __future__ import annotations

import json

import ifcopenshell
import pytest

from vectorworks_plugin_import_ifc_homeskz.document import (
    MemberCommand,
    StoryBoundCommand,
)
from vectorworks_plugin_import_ifc_homeskz.ifc.column import (
    _get_position_2d,
    _hardware_spec,
    _member_width_on_top,
    build_column_commands,
    make_column_member_id,
    resolve_column_type,
)
from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
    CLASS_MOYA,
    CLASS_NOKIGETA,
)


def _top_member(
    width: float, start: tuple[float, float], end: tuple[float, float],
    top_z: float, height: float = 90.0, member_class: str = CLASS_MOYA,
    layer: str = 'R-母屋',
) -> MemberCommand:
    """テスト用の横架材命令(母屋等)を組み立てる。

    ``top_z`` は天端の絶対 Z、断面下端は ``top_z - height``。
    """
    bound: StoryBoundCommand = {
        'story_offset': 0, 'level': '母屋', 'offset': 0.0}
    return {
        'layer': layer,
        'member_id': f'{int(width)}×{int(height)}',
        'class': member_class,
        'start': [float(start[0]), float(start[1])],
        'end': [float(end[0]), float(end[1])],
        'width': float(width),
        'height': float(height),
        'elevation': float(top_z),
        'end_elevation': float(top_z),
        'start_bound': bound,
        'end_bound': bound,
    }


# ---------------------------------------------------------------------------
# テスト用 IFC エンティティ生成ヘルパー
# ---------------------------------------------------------------------------

def make_storey(ifc: ifcopenshell.file, name: str, elevation: float) -> ifcopenshell.entity_instance:
    """テスト用 IfcBuildingStorey を生成する。"""
    return ifc.create_entity('IfcBuildingStorey', Name=name, Elevation=elevation)


def make_column(ifc: ifcopenshell.file, storey: ifcopenshell.entity_instance,
                ox: float, oy: float, oz: float = 0.0,
                width: float = 105.0, depth: float = 105.0, height: float = 2844.0,
                object_type: str | None = None,
                name: str | None = None) -> ifcopenshell.entity_instance:
    """テスト用 IfcColumn を生成して storey に追加する。

    Parameters
    ----------
    ox, oy, oz : 柱のローカル配置座標 (mm)。oz はストーリ原点からの相対 Z(負値)。
    width      : IfcRectangleProfileDef.XDim (断面幅, mm)
    depth      : IfcRectangleProfileDef.YDim (断面成, mm)
    height     : IfcExtrudedAreaSolid.Depth (柱高さ, mm)
    """
    # 配置(柱はローカル Z 方向に押し出される)
    pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[ox, oy, oz])
    placement_3d = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
    local_placement = ifc.create_entity('IfcLocalPlacement', RelativePlacement=placement_3d)

    # プロファイルと押し出しソリッド(押し出し方向 = ローカル Z)
    profile = ifc.create_entity(
        'IfcRectangleProfileDef', ProfileType='AREA', XDim=float(width), YDim=float(depth)
    )
    extrude_dir = ifc.create_entity('IfcDirection', DirectionRatios=[0.0, 0.0, 1.0])
    solid = ifc.create_entity(
        'IfcExtrudedAreaSolid', SweptArea=profile, ExtrudedDirection=extrude_dir, Depth=float(height)
    )

    wcs_pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
    wcs = ifc.create_entity('IfcAxis2Placement3D', Location=wcs_pt)
    ctx = ifc.create_entity(
        'IfcGeometricRepresentationContext', CoordinateSpaceDimension=3, WorldCoordinateSystem=wcs
    )
    shape_rep = ifc.create_entity(
        'IfcShapeRepresentation',
        ContextOfItems=ctx,
        RepresentationIdentifier='Body',
        RepresentationType='SweptSolid',
        Items=[solid],
    )
    prod_def = ifc.create_entity('IfcProductDefinitionShape', Representations=[shape_rep])

    column = ifc.create_entity(
        'IfcColumn', Name=name, ObjectPlacement=local_placement, Representation=prod_def,
        ObjectType=object_type,
    )

    ifc.create_entity(
        'IfcRelContainedInSpatialStructure', RelatingStructure=storey, RelatedElements=[column]
    )
    return column


def make_hardware(ifc: ifcopenshell.file, storey: ifcopenshell.entity_instance,
                  ox: float, oy: float, name: str, type_name: str,
                  oz: float = 0.0) -> ifcopenshell.entity_instance:
    """テスト用 柱頭/柱脚金物 (IfcMechanicalFastener) を生成して storey に追加する。

    name に ``柱頭金物`` / ``柱脚金物`` を含めると柱頭/柱脚として分類される。
    type_name は金物の型名(例: ``柱頭金物:(ろ)``)で、加工せずそのまま仕様になる。
    """
    pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[ox, oy, oz])
    placement_3d = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
    local_placement = ifc.create_entity('IfcLocalPlacement', RelativePlacement=placement_3d)

    fastener = ifc.create_entity(
        'IfcMechanicalFastener', Name=name, ObjectPlacement=local_placement
    )
    fastener_type = ifc.create_entity('IfcMechanicalFastenerType', Name=type_name)
    ifc.create_entity(
        'IfcRelDefinesByType', RelatedObjects=[fastener], RelatingType=fastener_type
    )
    ifc.create_entity(
        'IfcRelContainedInSpatialStructure', RelatingStructure=storey,
        RelatedElements=[fastener],
    )
    return fastener


def make_grid_axis(ifc: ifcopenshell.file, name: str,
                   x1: float, y1: float, x2: float, y2: float) -> None:
    """テスト用 IfcGridAxis を生成する(グリッド中心算出に使用)。"""
    pts = [
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x1, y1]),
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x2, y2]),
    ]
    polyline = ifc.create_entity('IfcPolyline', Points=pts)
    ifc.create_entity('IfcGridAxis', AxisTag=name, AxisCurve=polyline, SameSense=True)


# ---------------------------------------------------------------------------
# _get_position_2d
# ---------------------------------------------------------------------------

class TestGetPosition2D:
    def test_extracts_origin(self) -> None:
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[1000.0, 2000.0, -174.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        col = ifc.create_entity('IfcColumn', ObjectPlacement=lp)

        result = _get_position_2d(col)
        assert result is not None
        ox, oy = result
        assert ox == pytest.approx(1000.0)
        assert oy == pytest.approx(2000.0)

    def test_returns_none_when_no_placement(self) -> None:
        ifc = ifcopenshell.file()
        col = ifc.create_entity('IfcColumn')
        assert _get_position_2d(col) is None


# ---------------------------------------------------------------------------
# resolve_column_type
# ---------------------------------------------------------------------------

class TestResolveColumnType:
    def test_none_maps_to_kudabashira(self) -> None:
        assert resolve_column_type(None) == '管柱'

    def test_standcolumn_maps_to_koyazuka(self) -> None:
        assert resolve_column_type('STANDCOLUMN') == '小屋束'

    def test_unknown_falls_back_to_default(self) -> None:
        assert resolve_column_type('SOMETHING_ELSE') == '管柱'


# ---------------------------------------------------------------------------
# _hardware_spec
# ---------------------------------------------------------------------------

class TestHardwareSpec:
    def test_returns_type_name_unprocessed(self) -> None:
        """型名は加工せず(コロン分割せず)そのまま仕様文字列になる。"""
        assert _hardware_spec('柱頭金物:(ろ)') == '柱頭金物:(ろ)'
        assert _hardware_spec('柱脚金物:C12') == '柱脚金物:C12'

    def test_returns_whole_name_without_separator(self) -> None:
        assert _hardware_spec('HD-B20') == 'HD-B20'

    def test_returns_empty_for_none_or_empty(self) -> None:
        assert _hardware_spec(None) == ''
        assert _hardware_spec('') == ''


# ---------------------------------------------------------------------------
# make_column_member_id
# ---------------------------------------------------------------------------

class TestMakeColumnMemberId:
    def test_section_and_type_without_hardware(self) -> None:
        assert make_column_member_id(105, 105, '管柱', '', '') == '105×105 - 管柱'

    def test_rounds_dimensions(self) -> None:
        assert make_column_member_id(104.6, 120.4, '管柱', '', '') == '105×120 - 管柱'

    def test_appends_both_hardware(self) -> None:
        assert make_column_member_id(
            105, 105, '管柱', '柱頭金物:(ろ)', '柱脚金物:(い)'
        ) == '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(い)'

    def test_appends_only_present_hardware(self) -> None:
        assert make_column_member_id(
            105, 105, '小屋束', '柱頭金物:(ろ)', ''
        ) == '105×105 - 小屋束 / 柱頭金物:(ろ)'


# ---------------------------------------------------------------------------
# _member_width_on_top
# ---------------------------------------------------------------------------

class TestMemberWidthOnTop:
    def test_returns_width_of_member_resting_on_top(self) -> None:
        """小屋束上端に下端が接する母屋の幅を返す。"""
        moya = _top_member(90.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=7090.0)
        assert _member_width_on_top(0.0, 0.0, 7000.0, [moya]) == pytest.approx(90.0)

    def test_returns_none_when_no_member(self) -> None:
        assert _member_width_on_top(0.0, 0.0, 7000.0, []) is None

    def test_ignores_non_roof_top_member(self) -> None:
        """母屋・棟木・登り梁以外(軒桁等)は対象にしない。"""
        girder = _top_member(105.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=7090.0,
                             member_class=CLASS_NOKIGETA, layer='R-軒高')
        assert _member_width_on_top(0.0, 0.0, 7000.0, [girder]) is None

    def test_matches_member_pierced_by_post(self) -> None:
        """小屋束が母屋を貫いて天端付近まで伸びる(棟束等)場合も拾う。

        母屋の Z 範囲 [6754, 6859] に小屋束上端 6861(天端 +2mm)が収まる。
        """
        moya = _top_member(105.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=6859.0,
                           height=105.0)
        assert _member_width_on_top(0.0, 0.0, 6861.0, [moya]) == pytest.approx(105.0)

    def test_ignores_member_far_below(self) -> None:
        """Z 範囲が大きく離れた(下方の)材は対象にしない。"""
        low = _top_member(90.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=5000.0)
        assert _member_width_on_top(0.0, 0.0, 7000.0, [low]) is None

    def test_ignores_member_off_to_the_side(self) -> None:
        """平面上、小屋束が footprint の外(幅の外)にある材は対象にしない。"""
        moya = _top_member(90.0, (0.0, 500.0), (0.0, 1500.0), top_z=7090.0)
        # 小屋束 (0,0) は母屋の軸(y=500〜1500)から大きく外れる
        assert _member_width_on_top(0.0, 0.0, 7000.0, [moya]) is None

    def test_prefers_member_closest_to_top(self) -> None:
        """複数候補があれば下端が小屋束上端に最も近い材を選ぶ。"""
        near = _top_member(90.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=7090.0)
        far = _top_member(120.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=7110.0,
                          height=120.0)  # 下端 6990、小屋束上端 7000 から 10mm 下
        assert _member_width_on_top(0.0, 0.0, 7000.0, [far, near]) \
            == pytest.approx(90.0)

    def test_matches_sloped_noboribari_interpolated_z(self) -> None:
        """登り梁は小屋束位置で天端 Z を補間して Z 範囲を判定する。"""
        from vectorworks_plugin_import_ifc_homeskz.ifc.structural_class import (
            CLASS_NOBORIBARI,
        )
        # 始端 (−1000,0) 天端 6000 → 終端 (1000,0) 天端 8000 の傾斜梁(高さ 90)
        nb = _top_member(120.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=6000.0,
                         member_class=CLASS_NOBORIBARI, layer='R-登り梁')
        nb['end_elevation'] = 8000.0
        # 中央 (0,0) の天端は補間で 7000、下端 6910。小屋束上端 6950 は範囲内。
        assert _member_width_on_top(0.0, 0.0, 6950.0, [nb]) == pytest.approx(120.0)


# ---------------------------------------------------------------------------
# build_column_commands
# ---------------------------------------------------------------------------

class TestBuildColumnCommands:
    def test_empty_ifc_returns_empty_list(self) -> None:
        assert build_column_commands(ifcopenshell.file()) == []

    def test_builds_command_per_column(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_column(ifc, storey, 0.0, 0.0)
        make_column(ifc, storey, 1000.0, 0.0)
        make_storey(ifc, 'RFL', 6300.0)

        commands = build_column_commands(ifc)
        assert len(commands) == 2
        # 柱は span レイヤ ``{from}to{to}-柱`` に配置する。base(1 階=1 始まりレベル 1)
        # 起点なので from=1(``1to...``)。
        assert all(c['layer'].startswith('1to') and c['layer'].endswith('-柱')
                   for c in commands)
        # 構造材 ID は "{幅}×{成} - {種別}"(金物なし)
        assert all(c['member_id'] == '105×105 - 管柱' for c in commands)

    def test_top_story_uses_column_layer(self) -> None:
        """最上階の柱(小屋束等)も span レイヤに配置する(base = その階のレベル)。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0)

        commands = build_column_commands(ifc)
        assert len(commands) == 1
        # 単一ストーリ=レベル 1(1 始まり)。上に階が無いため屋根束扱いで 1to1.5。
        assert commands[0]['layer'] == '1to1.5-柱'
        # 下端高さ = ストーリ高さ + ローカル Z
        assert commands[0]['elevation'] == pytest.approx(6200.0)

    def test_column_binds_bottom_current_top_upper_floor(self) -> None:
        """柱(管柱・通し柱)は下端を当階、上端を上階の横架材天端にバインドする。

        offset はバインド先レベルの絶対 Z から実際の下端/上端 Z までの距離。
        当階(1FL)の横架材天端 = 600 + resolve_beam_top_offset、上階(2FL)の
        横架材天端 = 3500 + resolve_beam_top_offset。この IFC では柱以外に
        負の配置 Z を持つ要素が無いため beam_top_offset は 0(横架材天端 = FL 高さ)。
        """
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0, height=2718.0)

        command = build_column_commands(ifc)[0]
        # 下端=自階高さ+ローカル Z(600+0)、上端は elevation + height
        assert command['elevation'] == pytest.approx(600.0)
        assert command['height'] == pytest.approx(2718.0)
        # 下端は当階(story_offset=0)の横架材天端、offset = 600 - 600 = 0
        bottom = command['bottom_bound']
        assert bottom['story_offset'] == 0
        assert bottom['level'] == '横架材天端'
        assert bottom['offset'] == pytest.approx(0.0)
        # 上端は上階(story_offset=1)の横架材天端、offset = (600+2718) - 3500
        top = command['top_bound']
        assert top['story_offset'] == 1
        assert top['level'] == '横架材天端'
        assert top['offset'] == pytest.approx(600.0 + 2718.0 - 3500.0)

    def test_koyazuka_binds_both_ends_to_current_eaves(self) -> None:
        """小屋束は下端・上端とも当階の横架材天端(最上階は軒高)にバインドする。

        VW の構造材ツールは上下端 story bound の offset 差をパス由来の部材長に
        加算するため、パスが既に柱高さを持つ小屋束では上端 offset を下端と同値に
        して加算分を 0 にする(異なると柱高さが二重加算され上端が約 2 倍になる)。
        上端の実高さはパス(下端 + height)が担う。
        """
        ifc = ifcopenshell.file()
        make_storey(ifc, '1FL', 600.0)
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0, height=800.0,
                    object_type='STANDCOLUMN')

        command = build_column_commands(ifc)[0]
        # 最上階の柱(小屋束)は軒高(offset 0)を横架材天端の高さとする。
        # 下端 = 6300 - 100 = 6200、上端はパスの下端 + height = 7000。
        bottom = command['bottom_bound']
        top = command['top_bound']
        assert bottom['story_offset'] == 0
        assert bottom['level'] == '軒高'
        assert bottom['offset'] == pytest.approx(-100.0)
        # 上端 offset は下端と同値(offset 差 0 で二重加算を避ける)
        assert top['story_offset'] == 0
        assert top['level'] == '軒高'
        assert top['offset'] == pytest.approx(-100.0)

    def test_assigns_layer_per_story(self) -> None:
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        s2 = make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0)
        make_column(ifc, s2, 0.0, 0.0)

        layers = [c['layer'] for c in build_column_commands(ifc)]
        # 柱は span レイヤに配置する。1 階起点の柱は from=1(``1to...``)、2 階起点は
        # from=2(``2to...``)。
        assert any(lyr.startswith('1to') for lyr in layers)
        assert any(lyr.startswith('2to') for lyr in layers)

    def test_elevation_is_story_plus_local_z(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-174.0)

        commands = build_column_commands(ifc)
        assert commands[0]['elevation'] == pytest.approx(426.0)

    def test_applies_grid_center_offset(self) -> None:
        """グリッド中心オフセットを引いた座標で命令を組み立てることを確認する。"""
        ifc = ifcopenshell.file()
        # グリッド軸: X=0〜2000, Y=0〜2000 → center=(1000, 1000)
        make_grid_axis(ifc, 'X1', 0.0, 0.0, 2000.0, 0.0)
        make_grid_axis(ifc, 'Y1', 0.0, 0.0, 0.0, 2000.0)
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 柱 (1500, 1500): センタリング後 → (500, 500)
        make_column(ifc, storey, 1500.0, 1500.0)

        commands = build_column_commands(ifc)
        assert len(commands) == 1
        assert commands[0]['position'] == [pytest.approx(500.0), pytest.approx(500.0)]

    def test_sets_dimensions(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, width=105.0, depth=120.0, height=2844.0)

        command = build_column_commands(ifc)[0]
        assert command['width'] == pytest.approx(105.0)
        assert command['depth'] == pytest.approx(120.0)
        assert command['height'] == pytest.approx(2844.0)

    def test_standcolumn_object_type_maps_to_koyazuka(self) -> None:
        """ObjectType=STANDCOLUMN は member_id の種別が小屋束になる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, object_type='STANDCOLUMN')

        commands = build_column_commands(ifc)
        assert commands[0]['member_id'] == '105×105 - 小屋束'

    def test_standcolumn_class_is_koyazuka(self) -> None:
        """ObjectType=STANDCOLUMN の柱は小屋束クラスになる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, object_type='STANDCOLUMN')

        commands = build_column_commands(ifc)
        assert commands[0]['class'] == '04構造-02木造-05小屋組-02小屋束'

    def test_koyazuka_structural_use_is_koyazuka(self) -> None:
        """小屋束(最上階の柱)の構造用途は小屋束 "5" になる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, object_type='STANDCOLUMN')

        commands = build_column_commands(ifc)
        assert commands[0]['structural_use'] == '5'

    def test_general_column_structural_use_is_column(self) -> None:
        """一般階の柱(管柱・通し柱)の構造用途は柱 "4" になる。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0)

        commands = build_column_commands(ifc)
        assert commands[0]['structural_use'] == '4'

    def test_single_story_column_class_is_kudabashira(self) -> None:
        """1 階分で止まる一般階の柱は管柱クラスになる。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 上端 ≈ 600 + 2844 = 3444 < 2FL(3500) → 管柱
        make_column(ifc, s1, 0.0, 0.0, height=2844.0)

        commands = build_column_commands(ifc)
        assert commands[0]['class'] == '04構造-02木造-03柱-02管柱'

    def test_through_column_class_is_toshibashira(self) -> None:
        """上階の床を貫く(複数階を通す)柱は通し柱クラスになる。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 上端 ≈ 600 + 5700 = 6300 で 2FL(3500) を貫く → 通し柱
        make_column(ifc, s1, 0.0, 0.0, height=5700.0)

        commands = build_column_commands(ifc)
        assert commands[0]['class'] == '04構造-02木造-03柱-01通し柱'

    def test_skips_column_without_placement(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        column = ifc.create_entity('IfcColumn')  # 配置・ジオメトリなし
        ifc.create_entity(
            'IfcRelContainedInSpatialStructure', RelatingStructure=storey, RelatedElements=[column]
        )

        assert build_column_commands(ifc) == []

    def test_elevation_is_bottom_absolute_z(self) -> None:
        """下端 (elevation) は当該階の絶対 Z (ストーリ高さ + ローカル Z)。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, s1, 0.0, 0.0, oz=-174.0, height=2844.0)

        cmd = build_column_commands(ifc)[0]
        # 下端 = 600 - 174 = 426, 高さ = 2844 (上端は描画時に下端 + 高さ)
        assert cmd['elevation'] == pytest.approx(426.0)
        assert cmd['height'] == pytest.approx(2844.0)

    def test_hardware_defaults_to_empty_when_absent(self) -> None:
        """金物が無い柱は top_hardware / bottom_hardware が空文字になる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0)

        command = build_column_commands(ifc)[0]
        assert command['top_hardware'] == ''
        assert command['bottom_hardware'] == ''

    def test_matches_hardware_by_position(self) -> None:
        """同一平面座標の柱頭・柱脚金物の仕様を柱に対応付ける。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 1000.0, 2000.0)
        make_hardware(ifc, storey, 1000.0, 2000.0,
                      name='柱No.4:柱頭金物', type_name='柱頭金物:(ろ)', oz=2544.0)
        make_hardware(ifc, storey, 1000.0, 2000.0,
                      name='柱No.4:柱脚金物', type_name='柱脚金物:(い)', oz=-174.0)

        command = build_column_commands(ifc)[0]
        assert command['top_hardware'] == '柱頭金物:(ろ)'
        assert command['bottom_hardware'] == '柱脚金物:(い)'
        # 金物仕様は member_id にも連結される
        assert command['member_id'] == \
            '105×105 - 管柱 / 柱頭金物:(ろ) / 柱脚金物:(い)'

    def test_does_not_match_hardware_at_other_position(self) -> None:
        """別の平面座標の金物は対応付けない。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0)
        make_hardware(ifc, storey, 5000.0, 5000.0,
                      name='柱No.9:柱頭金物', type_name='柱頭金物:(ろ)')

        command = build_column_commands(ifc)[0]
        assert command['top_hardware'] == ''
        assert command['bottom_hardware'] == ''

    def test_koyazuka_width_matches_moya_on_top(self) -> None:
        """小屋束の断面は直上に乗る母屋の幅に合わせた正方形になる。

        90mm 幅の母屋が乗る 105×105 の小屋束は 90×90 に置き換わる。
        """
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        # 小屋束: 下端 6200・高さ 800 → 上端 7000、断面は IFC では 105×105(適当な値)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0, height=800.0,
                    width=105.0, depth=105.0, object_type='STANDCOLUMN')
        # 母屋(幅 90): 小屋束の真上に架かり、断面下端 = 7000(小屋束上端)に乗る
        moya = _top_member(90.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=7090.0)

        command = build_column_commands(ifc, [moya])[0]
        assert command['width'] == pytest.approx(90.0)
        assert command['depth'] == pytest.approx(90.0)
        # member_id も補正後の寸法で作られる
        assert command['member_id'] == '90×90 - 小屋束'

    def test_koyazuka_width_matches_105_moya(self) -> None:
        """105mm 幅の母屋が乗る小屋束は 105mm 角になる。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0, height=800.0,
                    width=90.0, depth=120.0, object_type='STANDCOLUMN')
        moya = _top_member(105.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=7105.0,
                           height=105.0)

        command = build_column_commands(ifc, [moya])[0]
        assert command['width'] == pytest.approx(105.0)
        assert command['depth'] == pytest.approx(105.0)

    def test_koyazuka_keeps_ifc_size_without_member_on_top(self) -> None:
        """上に乗る材が見つからない小屋束は IFC の断面をそのまま使う。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0, oz=-100.0, height=800.0,
                    width=105.0, depth=105.0, object_type='STANDCOLUMN')

        # 母屋を渡さない(上に乗る材が無い)
        command = build_column_commands(ifc, [])[0]
        assert command['width'] == pytest.approx(105.0)
        assert command['depth'] == pytest.approx(105.0)

    def test_general_column_not_resized_by_member(self) -> None:
        """管柱(小屋束でない柱)は上に材があっても断面を変えない。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, '2FL', 3500.0)
        make_storey(ifc, 'RFL', 6300.0)
        # 管柱: 105×120。仮に真上を通る母屋(幅 90)があっても影響しない
        make_column(ifc, s1, 0.0, 0.0, width=105.0, depth=120.0, height=2718.0)
        moya = _top_member(90.0, (-1000.0, 0.0), (1000.0, 0.0), top_z=3400.0)

        command = build_column_commands(ifc, [moya])[0]
        assert command['width'] == pytest.approx(105.0)
        assert command['depth'] == pytest.approx(120.0)

    def test_commands_are_json_serializable(self) -> None:
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 600.0)
        make_storey(ifc, 'RFL', 6300.0)
        make_column(ifc, storey, 0.0, 0.0)

        commands = build_column_commands(ifc)
        assert json.loads(json.dumps(commands)) == commands
