import re

import vs

CLASS_X = '01作図-01線-01基準線-01通り芯-X通り'
CLASS_Y = '01作図-01線-01基準線-01通り芯-Y通り'


def parse_ifc_content(content):
    """IFC テキストを解析し (points, polylines, grid_axes) を返す。

    points: {id: (x, y)}
    polylines: {id: [point_id, ...]}
    grid_axes: {id: {'name': str, 'poly_id': int}}
    """
    content = content.replace('\n', '').replace('\r', '')
    statements = content.split(';')

    points = {}
    polylines = {}
    grid_axes = {}

    pt_pattern = re.compile(r'#(\d+)\s*=\s*IFCCARTESIANPOINT\(\((.*?)\)\)')
    poly_pattern = re.compile(r'#(\d+)\s*=\s*IFCPOLYLINE\(\((.*?)\)\)')
    axis_pattern = re.compile(r"#(\d+)\s*=\s*IFCGRIDAXIS\('(.*?)',#(\d+),.*\)")

    for stmt in statements:
        if 'IFCCARTESIANPOINT' in stmt:
            match = pt_pattern.search(stmt)
            if match:
                id_val = int(match.group(1))
                coords = match.group(2).split(',')
                try:
                    x = float(coords[0].strip())
                    y = float(coords[1].strip())
                    points[id_val] = (x, y)
                except ValueError:
                    pass

        elif 'IFCPOLYLINE' in stmt:
            match = poly_pattern.search(stmt)
            if match:
                id_val = int(match.group(1))
                pt_ids_str = match.group(2).replace('#', '').split(',')
                pt_ids = [int(p.strip()) for p in pt_ids_str if p.strip().isdigit()]
                polylines[id_val] = pt_ids

        elif 'IFCGRIDAXIS' in stmt:
            match = axis_pattern.search(stmt)
            if match:
                id_val = int(match.group(1))
                name = match.group(2)
                poly_id = int(match.group(3))
                grid_axes[id_val] = {'name': name, 'poly_id': poly_id}

    return points, polylines, grid_axes


def resolve_lines(points, polylines, grid_axes):
    """グリッド軸を座標に解決し (lines_to_draw, center_x, center_y) を返す。

    lines_to_draw: [(x1, y1, x2, y2, name), ...]
    """
    lines_to_draw = []
    drawn_keys = set()

    min_x, max_x = float('inf'), float('-inf')
    min_y, max_y = float('inf'), float('-inf')

    for axis_data in grid_axes.values():
        name = axis_data['name']
        poly_id = axis_data['poly_id']

        if poly_id not in polylines:
            continue

        pt_ids = polylines[poly_id]
        for i in range(len(pt_ids) - 1):
            pt1_id, pt2_id = pt_ids[i], pt_ids[i + 1]

            if pt1_id not in points or pt2_id not in points:
                continue

            x1, y1 = points[pt1_id]
            x2, y2 = points[pt2_id]

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
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        vs.Message("IFCデータを解析中...")

        points, polylines, grid_axes = parse_ifc_content(content)
        lines_to_draw, center_x, center_y = resolve_lines(points, polylines, grid_axes)

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
