import vs

LEVEL_FL = 'FL'
LEVEL_BEAM_TOP = '横架材天端'
LEVEL_EAVES = '軒高'
STORY_ROOF = '屋根'


def get_local_placement_z(element):
    """IfcProduct のローカル配置 Z 座標 (浮動小数点) を取得する。取得できない場合は None。"""
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None or not placement.is_a('IfcLocalPlacement'):
        return None
    rel = placement.RelativePlacement
    if rel is None or not rel.is_a('IfcAxis2Placement3D'):
        return None
    loc = rel.Location
    if loc is None or not loc.is_a('IfcCartesianPoint'):
        return None
    coords = loc.Coordinates
    if len(coords) < 3:
        return None
    return float(coords[2])


def resolve_beam_top_offset(storey):
    """階に属する IfcColumn または IfcSlab から横架材天端の相対オフセット (FL からの負値) を求める。

    IFC のローカル配置 Z 座標が負の柱・床版が見つかればその値を返す。
    見つからなければ 0.0 を返す。
    """
    for rel in storey.ContainsElements or ():
        for element in rel.RelatedElements:
            if not (element.is_a('IfcColumn') or element.is_a('IfcSlab')):
                continue
            z = get_local_placement_z(element)
            if z is not None and z < 0:
                return z
    return 0.0


def collect_stories(ifc_file):
    """IFC からストーリ情報を集める。

    Returns: [(elevation, beam_offset_or_None), ...] を Elevation 昇順で返す。
        最上階は beam_offset=None (軒高のみ)、それ以外は beam_offset=負値 (横架材天端の FL からのオフセット)。

    名前が "FL" で終わらないストーリ (例: 設計GL) は地盤レベル等の参照高であり VW のストーリには
    しないため除外する。これを残すと既定高さ 0 のストーリが複数できて CreateStory が衝突する。
    """
    storeys = [
        s for s in ifc_file.by_type('IfcBuildingStorey')
        if (s.Name or '').upper().endswith('FL')
    ]
    storeys.sort(key=lambda s: float(s.Elevation or 0.0))
    result = []
    for i, storey in enumerate(storeys):
        elev = float(storey.Elevation or 0.0)
        if i == len(storeys) - 1:
            result.append((elev, None))
        else:
            result.append((elev, resolve_beam_top_offset(storey)))
    return result


def story_name_for(index, is_top):
    """index (0-origin) と最上階フラグから VectorWorks のストーリ名を返す。"""
    return STORY_ROOF if is_top else f'{index + 1}階'


def layer_prefix_for(index, is_top):
    """デザインレイヤ名の接頭辞を返す。"""
    return STORY_ROOF if is_top else str(index + 1)


def story_suffix_for(index, is_top):
    """CreateStory の suffix (前/後 記号) を返す。

    非空文字でないと 2 回目以降の CreateStory が失敗する。
    建築慣例の階表記に合わせ、一般階は階番号 ("1", "2", ...)、最上階は "R" (Roof)。
    """
    return 'R' if is_top else str(index + 1)


def create_story_layer(story_handle, level_type, elevation, layer_name):
    """ストーリレベル付きのデザインレイヤを作成し、(layer_handle, 診断文字列) を返す。

    呼び出し順序が重要:
      1. CreateLayer / SetLayerLevelType でレイヤを準備
      2. AddStoryLevelN で「指定 elevation」のストーリレベルを先に作る
      3. AssociateLayerWithStory でレイヤ ↔ ストーリ本体を関連付け
      4. SetLayerElevationN で念のため高さを上書き

    順序を逆 (Associate 先, Add 後) にすると、Associate がレベルタイプを
    elev=0 で暗黙的に作ってしまい、その後の AddStoryLevelN が
    "matches levelType or elevation" 制約で失敗してレベルが elev=0 のまま残る。
    """
    layer_h = vs.GetObject(layer_name)
    if layer_h == vs.Handle(0):
        layer_h = vs.CreateLayer(layer_name, 1)
    if layer_h == vs.Handle(0):
        return layer_h, f'CreateLayer({layer_name}) FAILED'

    slt = vs.SetLayerLevelType(layer_h, level_type)
    asl = vs.AddStoryLevelN(story_handle, level_type, elevation, layer_name)
    alws = vs.AssociateLayerWithStory(layer_h, story_handle)
    sle = vs.SetLayerElevationN(layer_h, elevation, 0.0)
    actual_z_result = vs.GetLayerElevationN(layer_h)
    actual_z = actual_z_result[0] if isinstance(actual_z_result, tuple) else actual_z_result
    return layer_h, (
        f'{layer_name}: SetLayerLevelType={slt}, AddStoryLevelN={asl}, '
        f'AssociateLayerWithStory={alws}, SetLayerElevationN={sle}, z={actual_z}'
    )


def import_stories(ifc_file):
    """IFC からストーリ・ストーリレベル・デザインレイヤを生成し、(階数, 診断行リスト) を返す。"""
    stories = collect_stories(ifc_file)
    if not stories:
        return 0, ['(IFC にストーリがありません)']

    cllt_fl = vs.CreateLayerLevelType(LEVEL_FL)
    cllt_bt = vs.CreateLayerLevelType(LEVEL_BEAM_TOP)
    cllt_ev = vs.CreateLayerLevelType(LEVEL_EAVES)

    n = len(stories)
    count = 0
    diag_lines = [
        f'CreateLayerLevelType: FL={cllt_fl}, 横架材天端={cllt_bt}, 軒高={cllt_ev}',
        f'IFC ストーリ数 = {n}',
    ]
    for i, (elevation, beam_offset) in enumerate(stories):
        is_top = i == n - 1
        story_name = story_name_for(i, is_top)
        diag_lines.append(f'--- [{i}] {story_name} (target elev={elevation}) ---')

        story_h = vs.GetObject(story_name)
        if story_h == vs.Handle(0):
            suffix = story_suffix_for(i, is_top)
            cs_result = vs.CreateStory(story_name, suffix)
            story_h = vs.GetObject(story_name)
            diag_lines.append(
                f'CreateStory(suffix={suffix!r}) -> {cs_result}, '
                f'GetObject後={"handle" if story_h != vs.Handle(0) else "null"}'
            )
        else:
            diag_lines.append('既存ストーリを再利用')

        if story_h == vs.Handle(0):
            diag_lines.append('★ ストーリ取得失敗、以降スキップ')
            continue

        se_result = vs.SetStoryElevationN(story_h, elevation)
        actual_elev = vs.GetStoryElevationN(story_h)
        diag_lines.append(f'SetStoryElevationN({elevation}) -> {se_result}, 実値={actual_elev}')

        prefix = layer_prefix_for(i, is_top)
        if is_top:
            _, ld = create_story_layer(story_h, LEVEL_EAVES, 0.0, f'{prefix}-{LEVEL_EAVES}')
            diag_lines.append('  ' + ld)
        else:
            _, ld1 = create_story_layer(story_h, LEVEL_FL, 0.0, f'{prefix}-{LEVEL_FL}')
            diag_lines.append('  ' + ld1)
            _, ld2 = create_story_layer(story_h, LEVEL_BEAM_TOP, beam_offset, f'{prefix}-{LEVEL_BEAM_TOP}')
            diag_lines.append('  ' + ld2)

        count += 1

    return count, diag_lines
