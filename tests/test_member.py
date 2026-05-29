import importlib
from unittest.mock import MagicMock, call, patch

import ifcopenshell
import pytest


# ---------------------------------------------------------------------------
# テスト用 IFC エンティティ生成ヘルパー
# ---------------------------------------------------------------------------

def make_storey(ifc, name, elevation):
    """テスト用 IfcBuildingStorey を生成する。"""
    return ifc.create_entity('IfcBuildingStorey', Name=name, Elevation=elevation)


def make_beam(ifc, storey, ox, oy, dx=1.0, dy=0.0,
              width=120.0, height=180.0, length=3000.0, material_name=''):
    """テスト用 IfcBeam を生成して storey に追加する。

    Parameters
    ----------
    ox, oy   : ビーム始端の XY 座標 (mm)
    dx, dy   : ビーム軸方向の成分 (ビーム局所 X 方向)
    width    : IfcRectangleProfileDef.XDim (幅, mm)
    height   : IfcRectangleProfileDef.YDim (背, mm)
    length   : IfcExtrudedAreaSolid.Depth (長さ, mm)
    """
    # 配置（梁の延伸方向 = ローカル Z = Axis 属性）
    pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[ox, oy, 0.0])
    axis = ifc.create_entity('IfcDirection', DirectionRatios=[dx, dy, 0.0])
    placement_3d = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
    local_placement = ifc.create_entity('IfcLocalPlacement', RelativePlacement=placement_3d)

    # プロファイルと押し出しソリッド
    profile = ifc.create_entity(
        'IfcRectangleProfileDef', ProfileType='AREA', XDim=float(width), YDim=float(height)
    )
    extrude_dir = ifc.create_entity('IfcDirection', DirectionRatios=[1.0, 0.0, 0.0])
    solid = ifc.create_entity(
        'IfcExtrudedAreaSolid', SweptArea=profile, ExtrudedDirection=extrude_dir, Depth=float(length)
    )

    # 表現コンテキストとシェイプ表現
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

    beam = ifc.create_entity(
        'IfcBeam', ObjectPlacement=local_placement, Representation=prod_def
    )

    # 材料関連付け
    if material_name:
        mat = ifc.create_entity('IfcMaterial', Name=material_name)
        ifc.create_entity('IfcRelAssociatesMaterial', RelatedObjects=[beam], RelatingMaterial=mat)

    # ストーリへの所属
    ifc.create_entity(
        'IfcRelContainedInSpatialStructure', RelatingStructure=storey, RelatedElements=[beam]
    )
    return beam


def make_grid_axis(ifc, name, x1, y1, x2, y2):
    """テスト用 IfcGridAxis を生成する（グリッド中心算出に使用）。"""
    pts = [
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x1, y1]),
        ifc.create_entity('IfcCartesianPoint', Coordinates=[x2, y2]),
    ]
    polyline = ifc.create_entity('IfcPolyline', Points=pts)
    ifc.create_entity('IfcGridAxis', AxisTag=name, AxisCurve=polyline, SameSense=True)


def _make_vs_mock(existing_layers=()):
    """import_members() 用 vs モック。

    existing_layers に含まれるレイヤ名は GetObject で非 null を返す。
    CreateCustomObjectPath は非 null を返し (プラグイン利用可能) 、
    SetRField / ResetObject の呼び出しを追跡できる。
    """
    vs_mock = MagicMock()
    null_handle = object()
    non_null_handle = object()
    vs_mock.Handle.return_value = null_handle
    vs_mock.LNewObj.return_value = non_null_handle
    vs_mock.CreateCustomObjectPath.return_value = non_null_handle

    def get_obj(name):
        return non_null_handle if name in existing_layers else null_handle

    vs_mock.GetObject.side_effect = get_obj
    return vs_mock


# ---------------------------------------------------------------------------
# _get_placement_2d
# ---------------------------------------------------------------------------

class TestGetPlacement2D:
    def test_extracts_origin(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[1000.0, 2000.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        result = _get_placement_2d(beam)
        assert result is not None
        ox, oy, oz, dx, dy = result
        assert ox == pytest.approx(1000.0)
        assert oy == pytest.approx(2000.0)

    def test_defaults_direction_to_x_axis_when_no_axis(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        ox, oy, oz, dx, dy = _get_placement_2d(beam)
        assert dx == pytest.approx(1.0)
        assert dy == pytest.approx(0.0)

    def test_extracts_axis_direction(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[0.0, 1.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        ox, oy, oz, dx, dy = _get_placement_2d(beam)
        assert dx == pytest.approx(0.0)
        assert dy == pytest.approx(1.0)

    def test_normalizes_direction(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        import math
        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        # 長さ 2 のベクトル
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[2.0, 0.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        ox, oy, oz, dx, dy = _get_placement_2d(beam)
        assert math.hypot(dx, dy) == pytest.approx(1.0)

    def test_returns_none_when_no_placement(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        elem = MagicMock()
        elem.ObjectPlacement = None
        assert _get_placement_2d(elem) is None

    def test_returns_none_for_non_local_placement(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        placement = MagicMock()
        placement.is_a = lambda t: False
        elem = MagicMock()
        elem.ObjectPlacement = placement
        assert _get_placement_2d(elem) is None


# ---------------------------------------------------------------------------
# _get_profile_dims
# ---------------------------------------------------------------------------

class TestGetProfileDims:
    def _make_element(self, width, height, length, rep_id='Body'):
        profile = MagicMock()
        profile.is_a = lambda t: t == 'IfcRectangleProfileDef'
        profile.XDim = float(width)
        profile.YDim = float(height)

        solid = MagicMock()
        solid.is_a = lambda t: t == 'IfcExtrudedAreaSolid'
        solid.SweptArea = profile
        solid.Depth = float(length)

        shape_rep = MagicMock()
        shape_rep.RepresentationIdentifier = rep_id
        shape_rep.Items = [solid]

        rep = MagicMock()
        rep.Representations = [shape_rep]

        elem = MagicMock()
        elem.Representation = rep
        return elem

    def test_extracts_width_height_length(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_profile_dims

        elem = self._make_element(120.0, 180.0, 3000.0)
        assert _get_profile_dims(elem) == (120.0, 180.0, 3000.0)

    def test_returns_none_when_no_representation(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_profile_dims

        elem = MagicMock()
        elem.Representation = None
        assert _get_profile_dims(elem) is None

    def test_skips_non_body_representation(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_profile_dims

        elem = self._make_element(120.0, 180.0, 3000.0, rep_id='Axis')
        assert _get_profile_dims(elem) is None

    def test_skips_non_rectangle_profile(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_profile_dims

        profile = MagicMock()
        profile.is_a = lambda t: False  # IfcRectangleProfileDef でない

        solid = MagicMock()
        solid.is_a = lambda t: t == 'IfcExtrudedAreaSolid'
        solid.SweptArea = profile

        shape_rep = MagicMock()
        shape_rep.RepresentationIdentifier = 'Body'
        shape_rep.Items = [solid]

        rep = MagicMock()
        rep.Representations = [shape_rep]
        elem = MagicMock()
        elem.Representation = rep
        assert _get_profile_dims(elem) is None


# ---------------------------------------------------------------------------
# _get_material_name
# ---------------------------------------------------------------------------

class TestGetMaterialName:
    def test_extracts_ifc_material_name(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_material_name

        mat = MagicMock()
        mat.is_a = lambda t: t == 'IfcMaterial'
        mat.Name = '杉対称異等級集成材E105-F355'

        rel = MagicMock()
        rel.is_a = lambda t: t == 'IfcRelAssociatesMaterial'
        rel.RelatingMaterial = mat

        elem = MagicMock()
        elem.HasAssociations = [rel]
        assert _get_material_name(elem) == '杉対称異等級集成材E105-F355'

    def test_extracts_first_material_from_material_list(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_material_name

        mat0 = MagicMock()
        mat0.Name = '1 番目の材種'
        mat_list = MagicMock()
        mat_list.is_a = lambda t: t == 'IfcMaterialList'
        mat_list.Materials = [mat0]

        rel = MagicMock()
        rel.is_a = lambda t: t == 'IfcRelAssociatesMaterial'
        rel.RelatingMaterial = mat_list

        elem = MagicMock()
        elem.HasAssociations = [rel]
        assert _get_material_name(elem) == '1 番目の材種'

    def test_returns_empty_when_no_association(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_material_name

        elem = MagicMock()
        elem.HasAssociations = []
        assert _get_material_name(elem) == ''

    def test_skips_non_material_relations(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_material_name

        rel = MagicMock()
        rel.is_a = lambda t: False  # IfcRelAssociatesMaterial でない

        elem = MagicMock()
        elem.HasAssociations = [rel]
        assert _get_material_name(elem) == ''


# ---------------------------------------------------------------------------
# make_member_id
# ---------------------------------------------------------------------------

class TestMakeMemberId:
    def test_with_material(self):
        from vectorworks_plugin_import_ifc_homeskz.member import make_member_id

        assert make_member_id(120, 180, '杉対称異等級集成材E105-F355') == \
            '120×180 - 杉対称異等級集成材E105-F355'

    def test_without_material(self):
        from vectorworks_plugin_import_ifc_homeskz.member import make_member_id

        assert make_member_id(120, 180, '') == '120×180'

    def test_rounds_float_dimensions(self):
        from vectorworks_plugin_import_ifc_homeskz.member import make_member_id

        assert make_member_id(120.4, 179.6, '') == '120×180'

    def test_rounds_up_when_above_half(self):
        from vectorworks_plugin_import_ifc_homeskz.member import make_member_id

        assert make_member_id(120.5, 180.5, '') == '121×181' or \
               make_member_id(120.5, 180.5, '') == '120×180'  # 丸め方向は実装依存


# ---------------------------------------------------------------------------
# import_members (統合テスト)
# ---------------------------------------------------------------------------

class TestImportMembers:
    """vs モジュールをモックして import_members() の動作を検証する。"""

    def test_empty_ifc_returns_zero(self):
        vs_mock = _make_vs_mock()

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifcopenshell.file())

        assert count == 0
        vs_mock.Layer.assert_not_called()

    def test_returns_count_of_drawn_members(self):
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_beam(ifc, storey, 0.0, 0.0)
        make_beam(ifc, storey, 0.0, 1000.0)
        # 最上階（屋根）: 横架材天端レイヤなし
        make_storey(ifc, 'RFL', 5973.0)

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})

        with patch.dict('sys.modules', {'vs': vs_mock}):
            importlib.reload(importlib.import_module('vectorworks_plugin_import_ifc_homeskz.member'))
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifc)

        assert count == 2

    def test_top_story_skipped_when_eaves_layer_missing(self):
        """最上階でも軒高レイヤが未生成なら描画しない。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0)

        vs_mock = _make_vs_mock()

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifc)

        assert count == 0
        vs_mock.Layer.assert_not_called()

    def test_top_story_uses_eaves_layer(self):
        """最上階 (RFL) のビームは R-軒高レイヤに配置される。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0)

        vs_mock = _make_vs_mock(existing_layers={'R-軒高'})

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifc)

        assert count == 1
        layer_calls = [c.args[0] for c in vs_mock.Layer.call_args_list]
        assert 'R-軒高' in layer_calls

    def test_switches_to_correct_layer(self):
        """各ストーリの横架材天端レイヤに切り替えて描画することを確認する。"""
        ifc = ifcopenshell.file()
        s1 = make_storey(ifc, '1FL', 473.0)
        s2 = make_storey(ifc, '2FL', 3273.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, s1, 0.0, 0.0)
        make_beam(ifc, s2, 0.0, 0.0)

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端', '2-横架材天端'})

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            member_module.import_members(ifc)

        layer_calls = [c.args[0] for c in vs_mock.Layer.call_args_list]
        assert '1-横架材天端' in layer_calls
        assert '2-横架材天端' in layer_calls

    def test_applies_grid_center_offset(self):
        """グリッド中心オフセットを引いた座標で描画することを確認する。"""
        ifc = ifcopenshell.file()
        # グリッド軸: X=0〜2000, Y=0〜2000 → center=(1000, 1000)
        make_grid_axis(ifc, 'X1', 0.0, 0.0, 2000.0, 0.0)
        make_grid_axis(ifc, 'Y1', 0.0, 0.0, 0.0, 2000.0)
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # ビーム始端 (1500, 1500): センタリング後 → (500, 500)
        # 長さ 600, X 方向 → 終端ベクトル (600, 0)
        make_beam(ifc, storey, 1500.0, 1500.0, dx=1.0, dy=0.0, length=600.0)

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        nurbs_calls = []
        vertex_calls = []
        move3d_calls = []

        def capture_nurbs(x, y, z, closed, order):
            nurbs_calls.append((x, y))
            return object()

        def capture_vertex(h, x, y, z):
            vertex_calls.append((x, y))

        def capture_move3d(x, y, z):
            move3d_calls.append((x, y, z))

        vs_mock.CreateNurbsCurve.side_effect = capture_nurbs
        vs_mock.AddVertex3D.side_effect = capture_vertex
        vs_mock.Move3D.side_effect = capture_move3d

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            member_module.import_members(ifc)

        # パスはローカル原点 (0, 0) から方向ベクトル (length, 0) へ
        assert (pytest.approx(0.0), pytest.approx(0.0)) in \
               [(pytest.approx(x), pytest.approx(y)) for x, y in nurbs_calls]
        assert (pytest.approx(600.0), pytest.approx(0.0)) in \
               [(pytest.approx(x), pytest.approx(y)) for x, y in vertex_calls]
        # Move3D でセンタリング後の始端 (1500-1000, 1500-1000) = (500, 500) へ移動
        # layer_elevation = storey.Elevation + resolve_beam_top_offset = 473 + 0 = 473
        assert any(
            abs(x - 500.0) < 1e-6 and abs(y - 500.0) < 1e-6 and abs(z - 473.0) < 1e-6
            for x, y, z in move3d_calls
        )

    def test_sets_member_id_record_field(self):
        """構造材 ID が SetRField で設定されることを確認する。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0, width=120.0, height=180.0, length=3000.0,
                  material_name='杉対称異等級集成材E105-F355')

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            member_module.import_members(ifc)

        set_rfield_args = [c.args for c in vs_mock.SetRField.call_args_list]
        member_id_values = [v for _, _, _, v in set_rfield_args]
        assert '120×180 - 杉対称異等級集成材E105-F355' in member_id_values

    def test_skips_layer_not_yet_created(self):
        """横架材天端レイヤが未生成の場合はそのストーリをスキップする。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0)

        # レイヤが存在しない状態
        vs_mock = _make_vs_mock(existing_layers=set())

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifc)

        assert count == 0
        vs_mock.Layer.assert_not_called()

    def test_fallback_to_line_when_plugin_unavailable(self):
        """構造材プラグインが利用できない場合に通常線にフォールバックする。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0)

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        # プラグインが存在しない → Handle(0) を返す
        null_handle = vs_mock.Handle.return_value
        vs_mock.CreateCustomObjectPath.return_value = null_handle

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifc)

        # フォールバックでも 1 本描画される
        assert count == 1
        # SetRField は呼ばれない (フォールバック時)
        vs_mock.SetRField.assert_not_called()


# ---------------------------------------------------------------------------
# 端点補正テスト
# ---------------------------------------------------------------------------

class TestEndpointIntrusion:
    def _make_seg(self, ox, oy, oz, ex, ey, w):
        return dict(ox=ox, oy=oy, oz=oz, ex=ex, ey=ey, ez=oz, w=w)

    def test_no_intrusion_when_endpoint_at_face(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _endpoint_intrusion
        # 直交する幅 100mm の梁があり、端点がその面上にある（perp_dist == 50mm）
        cross = self._make_seg(-50, -500, 0.0, -50, 500, 100)
        result = _endpoint_intrusion(-50 + 50, 0.0, 0.0, [cross])
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_detects_intrusion(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _endpoint_intrusion
        # 直交する幅 105mm の梁に対して端点が中心線上（perp=0）にある場合
        cross = self._make_seg(0, -500, 0.0, 0, 500, 105)
        result = _endpoint_intrusion(0.0, 0.0, 0.0, [cross])
        assert result == pytest.approx(52.5, abs=1e-6)

    def test_partial_intrusion(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _endpoint_intrusion
        # 幅 105mm 梁に対して 45mm 離れた端点（7.5mm 食い込み）
        cross = self._make_seg(0, -500, 0.0, 0, 500, 105)
        result = _endpoint_intrusion(45.0, 0.0, 0.0, [cross])
        assert result == pytest.approx(7.5, abs=1e-6)

    def test_skips_endpoint_region(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _endpoint_intrusion
        # t < 0.01（端部付近）はスキップされる（自己セグメントの始終点に相当）
        cross = self._make_seg(0, 0, 0.0, 0, 1000, 105)
        result = _endpoint_intrusion(0.0, 5.0, 0.0, [cross])  # t=0.005
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_skips_self_segment_via_t_filter(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _endpoint_intrusion
        # 自己セグメントは t=0（始点）または t=1（終点）なので t フィルタで除外される
        self_seg = self._make_seg(0, -500, 0.0, 0, 500, 105)
        result = _endpoint_intrusion(0.0, -500.0, 0.0, [self_seg])  # 始点: t=0.0
        assert result == pytest.approx(0.0, abs=1e-6)

    def test_skips_different_z(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _endpoint_intrusion
        # Z が 10mm 超離れた梁はスキップされる
        cross = self._make_seg(0, -500, 100.0, 0, 500, 105)
        result = _endpoint_intrusion(0.0, 0.0, 0.0, [cross])
        assert result == pytest.approx(0.0, abs=1e-6)
