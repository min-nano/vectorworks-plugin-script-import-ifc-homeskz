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


def create_story_layer(story_handle, level_type, elevation, layer_name):
    """ストーリレベル付きのデザインレイヤを作成し、レイヤハンドルを返す。

    処理順序: レイヤ作成 → レベルタイプ設定 → ストーリ関連付け → ストーリレベル追加 → 高さ強制上書き。
    高さ系 API は N 付き (document units) を使う。
    """
    layer_h = vs.GetObject(layer_name)
    if layer_h == vs.Handle(0):
        layer_h = vs.CreateLayer(layer_name, 1)
    if layer_h == vs.Handle(0):
        return layer_h

    vs.SetLayerLevelType(layer_h, level_type)
    vs.AssociateLayerWithStory(layer_h, story_handle)
    vs.AddStoryLevelN(story_handle, level_type, elevation, layer_name)
    vs.SetLayerElevationN(layer_h, elevation, 0.0)
    return layer_h


def import_stories(ifc_file):
    """IFC からストーリ・ストーリレベル・デザインレイヤを生成し、(階数, 診断情報) を返す。

    診断情報は [(story_name, intended_elev, actual_elev, [(layer_name, intended_z, actual_z), ...])] 形式。
    実機での値が意図通り設定されているか検証するためのもの。
    """
    stories = collect_stories(ifc_file)
    if not stories:
        return 0, []

    # レベルタイプを VW に登録する。未登録のまま SetLayerLevelType / AssociateLayerWithStory
    # を呼ぶとレイヤがストーリ基準座標系に切り替わらず、相対高さが反映されない。
    vs.CreateLayerLevelType(LEVEL_FL)
    vs.CreateLayerLevelType(LEVEL_BEAM_TOP)
    vs.CreateLayerLevelType(LEVEL_EAVES)

    n = len(stories)
    count = 0
    diagnostics = []
    for i, (elevation, beam_offset) in enumerate(stories):
        is_top = i == n - 1
        story_name = story_name_for(i, is_top)

        story_h = vs.GetObject(story_name)
        if story_h == vs.Handle(0):
            vs.CreateStory(story_name, '')
            story_h = vs.GetObject(story_name)
        if story_h == vs.Handle(0):
            continue

        # ストーリ高さは CreateStory 直後・レイヤ追加前に設定する。
        # 直後に設定しないと、次の CreateStory が「既定高さ 0 が既に占有されている」
        # と判断して失敗するケースがある (複数ストーリが全て高さ 0 で衝突するため)。
        vs.SetStoryElevationN(story_h, elevation)

        prefix = layer_prefix_for(i, is_top)
        layer_specs = []
        if is_top:
            lh = create_story_layer(story_h, LEVEL_EAVES, 0.0, f'{prefix}-{LEVEL_EAVES}')
            layer_specs.append((f'{prefix}-{LEVEL_EAVES}', 0.0, lh))
        else:
            lh1 = create_story_layer(story_h, LEVEL_FL, 0.0, f'{prefix}-{LEVEL_FL}')
            layer_specs.append((f'{prefix}-{LEVEL_FL}', 0.0, lh1))
            lh2 = create_story_layer(story_h, LEVEL_BEAM_TOP, beam_offset, f'{prefix}-{LEVEL_BEAM_TOP}')
            layer_specs.append((f'{prefix}-{LEVEL_BEAM_TOP}', beam_offset, lh2))

        # 診断: 実際に設定された値を取得
        actual_story_elev = vs.GetStoryElevationN(story_h)
        layer_diag = []
        for lname, intended_z, lh in layer_specs:
            if lh != vs.Handle(0):
                actual_z, _ = vs.GetLayerElevationN(lh)
            else:
                actual_z = None
            layer_diag.append((lname, intended_z, actual_z))
        diagnostics.append((story_name, elevation, actual_story_elev, layer_diag))

        count += 1

    return count, diagnostics
