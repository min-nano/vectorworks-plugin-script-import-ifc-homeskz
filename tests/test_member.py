import importlib
import math
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
              width=120.0, height=180.0, length=3000.0,
              material_name='', name=None,
              tree_type='', tree_class=''):
    """テスト用 IfcBeam を生成して storey に追加する。

    Parameters
    ----------
    ox, oy       : ビーム始端の XY 座標 (mm)
    dx, dy       : ビーム軸方向の成分 (ビーム局所 Z 方向 = Axis)
    width        : IfcRectangleProfileDef.XDim (幅, mm)
    height       : IfcRectangleProfileDef.YDim (背, mm)
    length       : IfcExtrudedAreaSolid.Depth (長さ, mm)
    material_name: IfcRelAssociatesMaterial で結合する材料名 (フォールバック用)
    name         : ビーム名 (例: '木口:梁:1')
    tree_type    : JPPset_TimberElementGeneral.TimberSpecies
    tree_class   : JPPset_TimberElementGeneral.StrengthClass
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
        'IfcBeam', ObjectPlacement=local_placement, Representation=prod_def,
        Name=name,
    )

    # JPPset_TimberElementGeneral を持つ IfcBeamType を作成
    if tree_type or tree_class:
        pset_props = []
        if tree_type:
            pset_props.append(ifc.create_entity(
                'IfcPropertySingleValue', Name='TimberSpecies',
                NominalValue=ifc.create_entity('IfcLabel', wrappedValue=tree_type),
            ))
        if tree_class:
            pset_props.append(ifc.create_entity(
                'IfcPropertySingleValue', Name='StrengthClass',
                NominalValue=ifc.create_entity('IfcLabel', wrappedValue=tree_class),
            ))
        pset = ifc.create_entity(
            'IfcPropertySet', Name='JPPset_TimberElementGeneral', HasProperties=pset_props
        )
        beam_type = ifc.create_entity('IfcBeamType', HasPropertySets=[pset])
        ifc.create_entity('IfcRelDefinesByType', RelatingType=beam_type, RelatedObjects=[beam])

    # 材料関連付け（フォールバック確認用）
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
    CreateCustomObject は非 null を返し (プラグイン利用可能)、
    SetRField / ResetObject の呼び出しを追跡できる。
    """
    vs_mock = MagicMock()
    null_handle = object()
    non_null_handle = object()
    vs_mock.Handle.return_value = null_handle
    vs_mock.LNewObj.return_value = non_null_handle
    vs_mock.CreateCustomObject.return_value = non_null_handle

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
        ox, oy, dx, dy = result
        assert ox == pytest.approx(1000.0)
        assert oy == pytest.approx(2000.0)

    def test_defaults_direction_to_x_axis_when_no_axis(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        ox, oy, dx, dy = _get_placement_2d(beam)
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

        ox, oy, dx, dy = _get_placement_2d(beam)
        assert dx == pytest.approx(0.0)
        assert dy == pytest.approx(1.0)

    def test_normalizes_direction(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_placement_2d

        ifc = ifcopenshell.file()
        pt = ifc.create_entity('IfcCartesianPoint', Coordinates=[0.0, 0.0, 0.0])
        axis = ifc.create_entity('IfcDirection', DirectionRatios=[2.0, 0.0, 0.0])
        ap = ifc.create_entity('IfcAxis2Placement3D', Location=pt, Axis=axis)
        lp = ifc.create_entity('IfcLocalPlacement', RelativePlacement=ap)
        beam = ifc.create_entity('IfcBeam', ObjectPlacement=lp)

        ox, oy, dx, dy = _get_placement_2d(beam)
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
        profile.is_a = lambda t: False

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
# _get_timber_properties
# ---------------------------------------------------------------------------

class TestGetTimberProperties:
    def _make_pset_mock(self, name, props):
        """IfcPropertySet モックを生成する。"""
        pset = MagicMock()
        pset.is_a = lambda t: t == 'IfcPropertySet'
        pset.Name = name
        prop_mocks = []
        for prop_name, value in props.items():
            p = MagicMock()
            p.is_a = lambda t, n=prop_name: t == 'IfcPropertySingleValue'
            p.Name = prop_name
            nv = MagicMock()
            nv.wrappedValue = value
            p.NominalValue = nv
            prop_mocks.append(p)
        pset.HasProperties = prop_mocks
        return pset

    def test_reads_from_beam_type_pset(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_timber_properties

        pset = self._make_pset_mock('JPPset_TimberElementGeneral', {
            'TimberSpecies': 'ひのき',
            'StrengthClass': 'E50(機械等級)',
        })
        beam_type = MagicMock()
        beam_type.HasPropertySets = [pset]

        rel_type = MagicMock()
        rel_type.is_a = lambda t: t == 'IfcRelDefinesByType'
        rel_type.RelatingType = beam_type

        elem = MagicMock()
        elem.IsDefinedBy = [rel_type]
        elem.HasAssociations = []

        tree_type, tree_class = _get_timber_properties(elem)
        assert tree_type == 'ひのき'
        assert tree_class == 'E50(機械等級)'

    def test_falls_back_to_material_association(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_timber_properties

        mat = MagicMock()
        mat.is_a = lambda t: t == 'IfcMaterial'
        mat.Name = '杉対称異等級集成材E105-F355'

        rel_mat = MagicMock()
        rel_mat.is_a = lambda t: t == 'IfcRelAssociatesMaterial'
        rel_mat.RelatingMaterial = mat

        elem = MagicMock()
        elem.IsDefinedBy = []
        elem.HasAssociations = [rel_mat]

        tree_type, tree_class = _get_timber_properties(elem)
        assert tree_type == '杉対称異等級集成材E105-F355'
        assert tree_class == ''

    def test_returns_empty_when_no_association(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_timber_properties

        elem = MagicMock()
        elem.IsDefinedBy = []
        elem.HasAssociations = []

        assert _get_timber_properties(elem) == ('', '')


# ---------------------------------------------------------------------------
# _get_kind_from_name
# ---------------------------------------------------------------------------

class TestGetKindFromName:
    def test_parses_beam_kind(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_kind_from_name

        assert _get_kind_from_name('木口:梁:1') == '梁'

    def test_parses_girder_kind(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_kind_from_name

        assert _get_kind_from_name('木口:桁:3') == '桁'

    def test_parses_sill_kind(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_kind_from_name

        assert _get_kind_from_name('木口:土台:2') == '土台'

    def test_defaults_to_beam_for_none(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_kind_from_name

        assert _get_kind_from_name(None) == '梁'

    def test_defaults_to_beam_for_unexpected_format(self):
        from vectorworks_plugin_import_ifc_homeskz.member import _get_kind_from_name

        assert _get_kind_from_name('unexpected') == '梁'


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
        """グリッド中心オフセットを引いた中心座標で CreateCustomObject を呼ぶことを確認する。"""
        ifc = ifcopenshell.file()
        # グリッド軸: X=0〜2000, Y=0〜2000 → center=(1000, 1000)
        make_grid_axis(ifc, 'X1', 0.0, 0.0, 2000.0, 0.0)
        make_grid_axis(ifc, 'Y1', 0.0, 0.0, 0.0, 2000.0)
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        # ビーム始端 (1500, 1500), X 方向, 長さ 600
        # センタリング後始端: (500, 500), 終端: (1100, 500)
        # 梁の中点: (800, 500), 角度: atan2(0, 600) = 0
        make_beam(ifc, storey, 1500.0, 1500.0, dx=1.0, dy=0.0, length=600.0)

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        create_calls = []
        rotate_calls = []
        move_calls = []

        def capture_create(name, x, y, angle):
            create_calls.append((name, x, y, angle))
            return vs_mock.Handle.return_value.__class__()  # non-null

        def capture_rotate(rx, ry, rz):
            rotate_calls.append((rx, ry, rz))

        def capture_move(x, y, z):
            move_calls.append((x, y, z))

        non_null = object()
        vs_mock.CreateCustomObject.side_effect = lambda *a: non_null
        vs_mock.Rotate3D.side_effect = capture_rotate
        vs_mock.Move3D.side_effect = capture_move

        # CreateCustomObject の呼び出しを追跡
        original_create = vs_mock.CreateCustomObject.side_effect
        vs_mock.CreateCustomObject.side_effect = None
        vs_mock.CreateCustomObject.return_value = non_null

        real_create_calls = []

        def track_create(name, x, y, angle):
            real_create_calls.append((name, x, y, angle))
            return non_null

        vs_mock.CreateCustomObject.side_effect = track_create

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            member_module.import_members(ifc)

        # CreateCustomObject は原点 (0, 0) に角度 0 で呼ばれる
        assert any(
            name == '梁・桁' and abs(x) < 1e-6 and abs(y) < 1e-6 and abs(angle) < 1e-6
            for name, x, y, angle in real_create_calls
        )
        # Move3D は梁の中点 (800, 500) に z=0 で呼ばれる
        assert any(
            abs(x - 800.0) < 1e-6 and abs(y - 500.0) < 1e-6 and abs(z) < 1e-6
            for x, y, z in move_calls
        )
        # Rotate3D は角度 0 で呼ばれる
        assert any(abs(rz) < 1e-6 for _, _, rz in rotate_calls)

    def test_sets_beam_record_fields(self):
        """梁・桁レコードに正しい値が SetRField で設定されることを確認する。"""
        ifc = ifcopenshell.file(schema='IFC2X3')  # ホームズ君 IFC は IFC2X3
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0, width=120.0, height=180.0, length=3000.0,
                  name='木口:梁:1',
                  tree_type='杉対称異等級集成材', tree_class='E105-F355')

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            member_module.import_members(ifc)

        set_rfield_calls = {(r, f): v for _, r, f, v in
                            [c.args for c in vs_mock.SetRField.call_args_list]}
        assert set_rfield_calls.get(('梁・桁', 'Width')) == '120'
        assert set_rfield_calls.get(('梁・桁', 'BeamHeight')) == '180'
        assert set_rfield_calls.get(('梁・桁', 'Height')) == '0'
        assert set_rfield_calls.get(('梁・桁', 'TreeType')) == '杉対称異等級集成材'
        assert set_rfield_calls.get(('梁・桁', 'TreeClass')) == 'E105-F355'
        assert set_rfield_calls.get(('梁・桁', 'Kind')) == '梁'
        assert set_rfield_calls.get(('梁・桁', 'Reference')) == '中心'
        assert set_rfield_calls.get(('梁・桁', 'Offset')) == '150'
        assert set_rfield_calls.get(('梁・桁', 'StartJoint')) == ' '
        assert set_rfield_calls.get(('梁・桁', 'EndJoint')) == ' '
        # ControlPoint01Y = height/2 + 150 = 180/2 + 150 = 240.0
        assert set_rfield_calls.get(('梁・桁', 'ControlPoint01Y')) == '240.0'

    def test_skips_layer_not_yet_created(self):
        """横架材天端レイヤが未生成の場合はそのストーリをスキップする。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0)

        vs_mock = _make_vs_mock(existing_layers=set())

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifc)

        assert count == 0
        vs_mock.Layer.assert_not_called()

    def test_fallback_to_line_when_plugin_unavailable(self):
        """梁・桁プラグインが利用できない場合に通常線にフォールバックする。"""
        ifc = ifcopenshell.file()
        storey = make_storey(ifc, '1FL', 473.0)
        make_storey(ifc, 'RFL', 5973.0)
        make_beam(ifc, storey, 0.0, 0.0)

        vs_mock = _make_vs_mock(existing_layers={'1-横架材天端'})
        # プラグインが存在しない → Handle(0) を返す
        null_handle = vs_mock.Handle.return_value
        vs_mock.CreateCustomObject.return_value = null_handle

        with patch.dict('sys.modules', {'vs': vs_mock}):
            import vectorworks_plugin_import_ifc_homeskz.member as member_module
            importlib.reload(member_module)
            count = member_module.import_members(ifc)

        # フォールバックでも 1 本描画される
        assert count == 1
        # フォールバック時は SetRField は呼ばれない
        vs_mock.SetRField.assert_not_called()
