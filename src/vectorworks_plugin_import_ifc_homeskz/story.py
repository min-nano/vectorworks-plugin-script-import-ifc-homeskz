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


def story_suffix_for(index, is_top):
    """CreateStory の suffix (前/後 記号) を返す。

    非空文字でないと 2 回目以降の CreateStory が失敗する。
    建築慣例の階表記に合わせ、一般階は階番号 ("1", "2", ...)、最上階は "R" (Roof)。
    """
    return 'R' if is_top else str(index + 1)


def layer_prefix_for(index, is_top):
    """デザインレイヤ名の接頭辞を返す (ストーリ suffix と同じ "1"/"2"/"R")。"""
    return story_suffix_for(index, is_top)


def create_story_level_via_template(story_handle, level_type, elevation, desired_layer_name):
    """Story Level Template 経由でストーリレベルとそれに紐づくレイヤを作成する。

    VW 2026 では AddStoryLevelN + AssociateLayerWithStory ではレイヤ→レベルの紐付けが
    UI 上 <なし> になるため、ドキュメントで明示的にバインドが保証されている
    CreateLevelTemplateN + AddLevelFromTemplate を使う。

    なお AddLevelFromTemplate は CreateStory の suffix を末尾に付加した名前で
    レイヤを作る (例: "1-FL-1")。意図した名前 ("1-FL") にするため、
    GetLayerForStory でハンドルを取り直して SetName でリネームする。
    """
    result = vs.CreateLevelTemplateN(desired_layer_name, 1.0, level_type, elevation, 2400.0)
    if isinstance(result, tuple):
        ok, template_idx = result
    else:
        ok, template_idx = bool(result), -1

    if not (ok and template_idx is not None and template_idx >= 0):
        return
    if not vs.AddLevelFromTemplate(story_handle, template_idx):
        return
    layer_h = vs.GetLayerForStory(story_handle, level_type)
    if layer_h != vs.Handle(0):
        vs.SetName(layer_h, desired_layer_name)


def import_stories(ifc_file):
    """IFC からストーリ・ストーリレベル・デザインレイヤを生成し、作成階数を返す。"""
    stories = collect_stories(ifc_file)
    if not stories:
        return 0

    vs.CreateLayerLevelType(LEVEL_FL)
    vs.CreateLayerLevelType(LEVEL_BEAM_TOP)
    vs.CreateLayerLevelType(LEVEL_EAVES)

    n = len(stories)
    count = 0
    for i, (elevation, beam_offset) in enumerate(stories):
        is_top = i == n - 1
        story_name = story_name_for(i, is_top)

        story_h = vs.GetObject(story_name)
        if story_h == vs.Handle(0):
            vs.CreateStory(story_name, story_suffix_for(i, is_top))
            story_h = vs.GetObject(story_name)
        if story_h == vs.Handle(0):
            continue

        # ストーリ高さは CreateStory 直後・レベル追加前に設定する。
        # 直後に設定しないと「既定高さ 0 のストーリが複数」となり次の
        # CreateStory が衝突して失敗するケースがある。
        vs.SetStoryElevationN(story_h, elevation)

        prefix = layer_prefix_for(i, is_top)
        if is_top:
            level_specs = [(LEVEL_EAVES, 0.0, f'{prefix}-{LEVEL_EAVES}')]
        else:
            level_specs = [
                (LEVEL_FL, 0.0, f'{prefix}-{LEVEL_FL}'),
                (LEVEL_BEAM_TOP, beam_offset, f'{prefix}-{LEVEL_BEAM_TOP}'),
            ]
        for level_type, level_offset, layer_name in level_specs:
            create_story_level_via_template(story_h, level_type, level_offset, layer_name)

        count += 1

    return count
