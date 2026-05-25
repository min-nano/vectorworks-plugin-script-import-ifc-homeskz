import ifcopenshell

import vs

CLASS_X = '01作図-01線-01基準線-01通り芯-X通り'
CLASS_Y = '01作図-01線-01基準線-01通り芯-Y通り'


def resolve_lines(ifc_file):
    """IfcGridAxis エンティティを座標に解決し (lines_to_draw, center_x, center_y) を返す。

    lines_to_draw: [(x1, y1, x2, y2, name), ...]
    """
    lines_to_draw = []
    drawn_keys = set()

    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')

    for axis in ifc_file.by_type('IfcGridAxis'):
        name = axis.AxisTag or ''
        curve = axis.AxisCurve
        if curve is None or not curve.is_a('IfcPolyline'):
            continue

        pts = [(float(pt.Coordinates[0]), float(pt.Coordinates[1])) for pt in curve.Points]

        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i + 1]

            line_key = tuple(sorted(((x1, y1), (x2, y2))))
            if line_key in drawn_keys:
                continue
            drawn_keys.add(line_key)

            min_x = min(min_x, x1, x2)
            max_x = max(max_x, x1, x2)
            min_y = min(min_y, y1, y2)
            max_y = max(max_y, y1, y2)

            lines_to_draw.append((x1, y1, x2, y2, name))

    if lines_to_draw:
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
    else:
        center_x = 0.0
        center_y = 0.0

    return lines_to_draw, center_x, center_y


def determine_class(name, cx1, cy1, cx2, cy2):
    """グリッド線のクラス名（X通り or Y通り）を返す。"""
    if name.upper().startswith('X'):
        return CLASS_X
    elif name.upper().startswith('Y'):
        return CLASS_Y
    else:
        return CLASS_X if abs(cx1 - cx2) < abs(cy1 - cy2) else CLASS_Y


def run():
    ok, filepath = vs.GetFileN("IFCファイルを選択してください", "", "ifc")
    if not ok:
        vs.AlrtDialog("キャンセルされました。")
        return

    try:
        vs.Message("IFCデータを解析中...")

        ifc_file = ifcopenshell.open(filepath)
        lines_to_draw, center_x, center_y = resolve_lines(ifc_file)

        target_layer = '共通'
        if vs.GetObject(target_layer) == vs.Handle(0):
            vs.CreateLayer(target_layer, 1)
        vs.Layer(target_layer)

        count = 0
        for x1, y1, x2, y2, name in lines_to_draw:
            cx1, cy1 = x1 - center_x, y1 - center_y
            cx2, cy2 = x2 - center_x, y2 - center_y

            current_class = determine_class(name, cx1, cy1, cx2, cy2)

            vs.BeginPoly()
            vs.MoveTo(cx1, cy1)
            vs.LineTo(cx2, cy2)
            vs.EndPoly()
            path_handle = vs.LNewObj()

            vs.BeginGroup()
            vs.EndGroup()
            profile_handle = vs.LNewObj()

            grid_obj = vs.CreateCustomObjectPath('GridAxis', path_handle, profile_handle)

            if grid_obj != vs.Handle(0):
                vs.SetClass(grid_obj, current_class)
                vs.SetRField(grid_obj, 'GridAxis', 'Label', name)
                vs.SetRField(grid_obj, 'GridAxis', 'ShowBubbleAt', 'Start Point')
                vs.ResetObject(grid_obj)
            else:
                vs.MoveTo(cx1, cy1)
                vs.LineTo(cx2, cy2)
                fallback_line = vs.LNewObj()
                vs.SetClass(fallback_line, current_class)

            count += 1

        vs.ClrMessage()
        vs.AlrtDialog(f"読込完了: 「{target_layer}」レイヤに、{count} 本の通り芯をそれぞれのクラスに振り分けて配置しました。")

    except Exception as e:
        vs.ClrMessage()
        vs.AlrtDialog(f"エラーが発生しました: {str(e)}")
