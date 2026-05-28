"""横架材天端レイヤに土台・梁・桁を描画するモジュール。

IFC の IfcBeam / IfcMember を走査し、各階の横架材天端レイヤに
VectorWorks 梁・桁ツール (CreateCustomObject('梁・桁', ...)) で配置する。
"""
import math

import vs

from .grid import resolve_lines
from .story import LEVEL_BEAM_TOP, LEVEL_EAVES, layer_prefix_for, resolve_beam_top_offset

PLUGIN_NAME = '梁・桁'

LAYER_SUFFIX = LEVEL_BEAM_TOP
_IFC_MEMBER_TYPES = ('IfcBeam', 'IfcMember')


def _get_placement_2d(element):
    """IfcProduct のローカル配置から 2D 座標 (ox, oy, dx, dy) を返す。

    取得できない場合は None を返す。
    dx, dy は梁軸方向の単位ベクトル（Axis の XY 成分）。
    ホームズ君 IFC では押し出し方向が常にローカル Z (Axis) なので
    梁の延伸方向 = Axis 属性を使う。Axis が未設定の場合は (1.0, 0.0) を使う。
    """
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None or not placement.is_a('IfcLocalPlacement'):
        return None
    rel = placement.RelativePlacement
    if rel is None or not rel.is_a('IfcAxis2Placement3D'):
        return None
    loc = rel.Location
    if loc is None:
        return None
    coords = loc.Coordinates
    ox, oy = float(coords[0]), float(coords[1])

    axis = rel.Axis
    if axis is not None and len(axis.DirectionRatios) >= 2:
        dx = float(axis.DirectionRatios[0])
        dy = float(axis.DirectionRatios[1])
        norm = math.hypot(dx, dy)
        if norm > 0.0:
            dx, dy = dx / norm, dy / norm
        else:
            dx, dy = 1.0, 0.0
    else:
        dx, dy = 1.0, 0.0

    return ox, oy, dx, dy


def _get_profile_dims(element):
    """IfcProduct の体ジオメトリから断面寸法 (width, height, length) を返す。

    Body 表現の IfcExtrudedAreaSolid + IfcRectangleProfileDef を解析する。
    見つからない場合は None を返す。
    """
    rep = getattr(element, 'Representation', None)
    if rep is None:
        return None
    for shape_rep in rep.Representations:
        if shape_rep.RepresentationIdentifier != 'Body':
            continue
        for item in shape_rep.Items:
            if not item.is_a('IfcExtrudedAreaSolid'):
                continue
            area = item.SweptArea
            if not area.is_a('IfcRectangleProfileDef'):
                continue
            return float(area.XDim), float(area.YDim), float(item.Depth)
    return None


def _get_timber_properties(element):
    """IfcProduct とその型から材種 (tree_type) と強度等級 (tree_class) を返す。

    IfcBeamType に関連付けられた JPPset_TimberElementGeneral プロパティセットを
    優先して参照し、見つからない場合は IfcRelAssociatesMaterial の材料名を
    tree_type として返す。いずれも見つからない場合は ('', '') を返す。
    """

    def _read_pset(pset):
        if not pset.is_a('IfcPropertySet'):
            return None
        if pset.Name != 'JPPset_TimberElementGeneral':
            return None
        species, grade = '', ''
        for prop in pset.HasProperties:
            if not prop.is_a('IfcPropertySingleValue') or prop.NominalValue is None:
                continue
            if prop.Name == 'TimberSpecies':
                species = str(prop.NominalValue.wrappedValue)
            elif prop.Name == 'StrengthClass':
                grade = str(prop.NominalValue.wrappedValue)
        if species or grade:
            return species, grade
        return None

    # IfcBeamType 経由で JPPset_TimberElementGeneral を探す
    for rel in getattr(element, 'IsDefinedBy', ()):
        if rel.is_a('IfcRelDefinesByType'):
            element_type = rel.RelatingType
            for pset in getattr(element_type, 'HasPropertySets', ()):
                result = _read_pset(pset)
                if result:
                    return result

    # element 直属の property sets を確認
    for rel in getattr(element, 'IsDefinedBy', ()):
        if rel.is_a('IfcRelDefinesByProperties'):
            result = _read_pset(rel.RelatingPropertyDefinition)
            if result:
                return result

    # フォールバック: IfcRelAssociatesMaterial の材料名を tree_type として使用
    for rel in getattr(element, 'HasAssociations', ()):
        if not rel.is_a('IfcRelAssociatesMaterial'):
            continue
        mat = rel.RelatingMaterial
        if mat.is_a('IfcMaterial') and mat.Name:
            return mat.Name, ''
        if mat.is_a('IfcMaterialList') and mat.Materials:
            return mat.Materials[0].Name or '', ''
        if mat.is_a('IfcMaterialLayerSetUsage'):
            layers = mat.ForLayerSet.MaterialLayers
            if layers:
                return layers[0].Material.Name or '', ''

    return '', ''


def _get_kind_from_name(name):
    """IFC 要素名 '木口:{kind}:{num}' から材種別 (梁・桁・土台 等) を返す。

    ホームズ君 IFC の名前形式 '木口:土台:1'、'木口:梁:2' などを想定する。
    形式に合わない場合は '梁' を返す。
    """
    if name:
        parts = name.split(':')
        if len(parts) >= 2:
            return parts[1]
    return '梁'


def _draw_member(x1, y1, x2, y2, width, height, tree_type, tree_class, kind):
    """梁・桁ツールで 1 本の部材を描画する。

    VectorScript のエクスポートパターンと同様に、まず原点に配置してから
    回転 (Rotate3D) と移動 (Move3D) で実際の位置へ変換する。
    Reference='中心' を使うため挿入点は梁の中点になる。
    プラグインが利用できない場合は通常の直線にフォールバックする。
    """
    length = math.hypot(x2 - x1, y2 - y1)
    if length < 1.0:
        return

    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    angle = math.atan2(y2 - y1, x2 - x1)

    w = int(round(width))
    h = int(round(height))

    obj = vs.CreateCustomObject(PLUGIN_NAME, 0, 0, 0)
    if obj == vs.Handle(0):
        vs.MoveTo(x1, y1)
        vs.LineTo(x2, y2)
        vs.LNewObj()
        return

    vs.ResetOrientation3D()
    vs.Rotate3D(0, 0, angle)
    vs.Move3D(cx, cy, 0)

    vs.SetRField(obj, PLUGIN_NAME, 'Height', '0')
    vs.SetRField(obj, PLUGIN_NAME, 'BeamType', '水平梁')
    vs.SetRField(obj, PLUGIN_NAME, 'Reference', '中心')
    vs.SetRField(obj, PLUGIN_NAME, 'BeamHeight', str(h))
    vs.SetRField(obj, PLUGIN_NAME, 'Width', str(w))
    vs.SetRField(obj, PLUGIN_NAME, 'LineLength', str(length))
    vs.SetRField(obj, PLUGIN_NAME, 'ShowJoint', 'False')
    vs.SetRField(obj, PLUGIN_NAME, 'StartJointLength', '0')
    vs.SetRField(obj, PLUGIN_NAME, 'EndJointLength', '0')
    vs.SetRField(obj, PLUGIN_NAME, 'StartBevel', '0°')
    vs.SetRField(obj, PLUGIN_NAME, 'EndBevel', '0°')
    vs.SetRField(obj, PLUGIN_NAME, 'StartCutShape', '垂直')
    vs.SetRField(obj, PLUGIN_NAME, 'EndCutShape', '垂直')
    vs.SetRField(obj, PLUGIN_NAME, 'StartJoint', ' ')
    vs.SetRField(obj, PLUGIN_NAME, 'EndJoint', ' ')
    vs.SetRField(obj, PLUGIN_NAME, 'TreeType', tree_type)
    vs.SetRField(obj, PLUGIN_NAME, 'TreeClass', tree_class)
    vs.SetRField(obj, PLUGIN_NAME, 'Offset', '150')
    vs.SetRField(obj, PLUGIN_NAME, 'ControlPoint01X', str(length / 2.0))
    vs.SetRField(obj, PLUGIN_NAME, 'ControlPoint01Y', str(height / 2.0 + 150.0))
    vs.SetRField(obj, PLUGIN_NAME, 'Kind', kind)
    vs.ResetObject(obj)


def import_members(ifc_file):
    """IFC の横架材 (IfcBeam / IfcMember) を各階の横架材天端レイヤに描画し、配置数を返す。

    配置座標は通り芯と同じグリッド中心オフセットで補正する。
    最上階（屋根）には横架材天端レイヤが存在しないため軒高レイヤに描画する。
    """
    _, center_x, center_y = resolve_lines(ifc_file)

    storeys = sorted(
        [s for s in ifc_file.by_type('IfcBuildingStorey')
         if (s.Name or '').upper().endswith('FL')],
        key=lambda s: float(s.Elevation or 0.0),
    )
    if not storeys:
        return 0

    top_idx = len(storeys) - 1
    count = 0

    for i, storey in enumerate(storeys):
        is_top = (i == top_idx)
        prefix = layer_prefix_for(i, is_top)
        layer_suffix = LEVEL_EAVES if is_top else LAYER_SUFFIX
        layer_name = f'{prefix}-{layer_suffix}'

        if vs.GetObject(layer_name) == vs.Handle(0):
            continue
        vs.Layer(layer_name)

        for rel in storey.ContainsElements:
            for element in rel.RelatedElements:
                if not any(element.is_a(t) for t in _IFC_MEMBER_TYPES):
                    continue

                placement = _get_placement_2d(element)
                if placement is None:
                    continue
                dims = _get_profile_dims(element)
                if dims is None:
                    continue

                ox, oy, dx, dy = placement
                width, height, length = dims

                x1 = ox - center_x
                y1 = oy - center_y
                x2 = x1 + dx * length
                y2 = y1 + dy * length

                tree_type, tree_class = _get_timber_properties(element)
                kind = _get_kind_from_name(getattr(element, 'Name', None))

                _draw_member(x1, y1, x2, y2, width, height, tree_type, tree_class, kind)
                count += 1

    return count
