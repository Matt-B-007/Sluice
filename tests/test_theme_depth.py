# SPDX-License-Identifier: GPL-3.0-or-later
"""Every look on every theme: depth colours worked out from the theme, readable small text, visible handles and channel colours,
keys that stand out from their tray, and each theme keeping its own identity (0.11.5)."""
import glob
from pathlib import Path

import pytest

from sluice import depth, skin_tile, themes
from sluice.model import Mixer

PACK = Path(__file__).resolve().parent.parent / "themes"


def all_themes():
    found = list(themes.BUILT_IN.values())
    found += [themes.load_file(path)[0] for path in sorted(glob.glob(str(PACK / "*.json")))]
    return found


THEMES = all_themes()


def test_there_are_28_themes():
    assert len(THEMES) == 28


@pytest.mark.parametrize("skin", list(themes.SKINS))
def test_small_text_handles_and_channel_colours_can_be_seen_in_every_theme(skin):
    problems = []
    for theme in THEMES:
        c = themes.skin_colors(theme, skin)
        d = depth.depth_colors(c, flat=skin_tile.is_flat(c))
        for surface in ("panel", "bg", "surface2"):
            if themes.contrast_ratio(c["text_off"], c[surface]) < themes.TEXT_OFF_MINIMUM:
                problems.append((theme.name, "greyed-out text on", surface))
        if themes.contrast_ratio(c["live_fg"], c["live_bg"]) < 4.5:
            problems.append((theme.name, "Live label"))
        if themes.contrast_ratio(c["mute_fg"], c["mute_bg"]) < 4.5:
            problems.append((theme.name, "muted button"))
        if d["light"]:
            if depth.contrast(c["handle_edge"], c["track"]) < 3:
                problems.append((theme.name, "slider handle on its groove"))
            for tint in skin_tile.CHANNEL_TINTS.values():
                shown = depth.channel_tint(tint, c)
                if depth.contrast(shown, d["groove"]) < 3 or depth.contrast(shown, c["panel"]) < 3:
                    problems.append((theme.name, "channel colour", tint, shown))
        if not d["flat"] and depth.contrast(d["key_top"], d["tray_bottom"]) < 1.15:
            problems.append((theme.name, "keys do not stand out from the tray"))
        if depth.contrast(d["groove"], d["key_bottom"]) < 1.15:
            problems.append((theme.name, "the groove does not show on the key"))
    assert problems == []


def test_shading_keeps_the_hue_of_a_strongly_coloured_theme():
    import colorsys

    synthwave = themes.load_file(PACK / "synthwave.json")[0]
    d = depth.depth_colors(synthwave.colors)
    hue = colorsys.rgb_to_hls(*depth._rgb(synthwave.colors["panel"]))[0]
    for name in ("key_top", "key_bottom", "key_skirt"):
        h, lightness, s = colorsys.rgb_to_hls(*depth._rgb(d[name]))
        assert s > 0.2 and abs(h - hue) < 0.02, name  # still indigo, not grey


def test_very_dark_themes_get_lit_edges_instead_of_shadows():
    oled = themes.load_file(PACK / "oled-black.json")[0]
    d = depth.depth_colors(oled.colors)
    assert d["very_dark"] and d["edge_light"] and d["shadow_alpha"] < 0.3
    assert depth.luminance(d["tray_top"]) > depth.luminance(oled.colors["bg"])  # the tray is lighter than a black floor


def test_high_contrast_is_flat_and_light_themes_have_no_glow():
    contrast = themes.BUILT_IN["contrast"].colors
    assert skin_tile.is_flat(contrast)
    d = depth.depth_colors(contrast, flat=True)
    assert d["flat"] and d["shadow_alpha"] == 0 and d["key_top"] == d["key_bottom"] and not d["glow"]
    assert not depth.depth_colors(themes.BUILT_IN["light"].colors)["glow"]
    assert depth.depth_colors(themes.BUILT_IN["dark"].colors)["glow"]


def test_shadows_are_tinted_by_the_theme_not_black():
    desert = themes.load_file(PACK / "desert.json")[0]
    shadow = depth.depth_colors(desert.colors)["shadow"]
    r, g, b = depth._rgb(shadow)
    assert shadow != "#000000" and r >= b  # a warm theme casts a warm shadow


def test_a_theme_file_can_set_depth_colours_by_hand():
    colors = dict(themes.BUILT_IN["dark"].colors, tray_top="#123456")
    assert depth.depth_colors(colors)["tray_top"] == "#123456"


@pytest.mark.parametrize("skin", ["nexus", "tile", "calm", "glass"])
def test_look_colours_replace_only_dark_and_light(skin):
    themes.set_skin_colors(True)
    try:
        dark = themes.skin_colors(themes.BUILT_IN["dark"], skin)
        assert dark["bg"] != themes.finish(themes.BUILT_IN["dark"].colors)["bg"]
        seen = {}
        others = ("purple", "midnight", "amber", "contrast") + (() if skin == "nexus" else ("paper",))  # (Nexus is dark only)
        for theme_id in others:
            shown = themes.skin_colors(themes.BUILT_IN[theme_id], skin)
            assert shown["bg"] == themes.BUILT_IN[theme_id].colors["bg"], theme_id  # every other theme keeps its own colours
            seen[shown["bg"]] = theme_id
        assert len(seen) == len(others)  # and they all still look different from each other
        light = themes.skin_colors(themes.BUILT_IN["light"], skin)
        paper = themes.skin_colors(themes.BUILT_IN["paper"], skin)
        assert light["panel"] != paper["panel"] or skin == "nexus"
        themes.set_skin_colors(False)
        assert themes.skin_colors(themes.BUILT_IN["dark"], skin)["bg"] == themes.BUILT_IN["dark"].colors["bg"]
    finally:
        themes.set_skin_colors(True)


def test_the_look_colours_setting_is_one_switch_and_old_settings_carry_over():
    assert Mixer.demo().skin_colors is True
    data = Mixer.demo().to_dict()
    assert data["skin_colors"] is True and "look_colors" not in data and "nexus_colors" not in data and "tile_colors" not in data
    for old, expected in (({"nexus_colors": False, "tile_colors": False}, False), ({"nexus_colors": False}, True),
                          ({"tile_colors": False}, True), ({}, True), ({"look_colors": False, "nexus_colors": True}, False)):
        data = Mixer.demo().to_dict()
        data.pop("skin_colors")
        data.update(old)
        assert Mixer.from_dict(data).skin_colors is expected, old


def test_a_theme_file_with_depth_colours_loads_and_exports_them(tmp_path):
    theme, notes = themes.parse({"name": "Deep", "base": "dark", "colors": {"tray_top": "#102030", "groove": "#000"}})
    assert notes == [] and theme.colors["tray_top"] == "#102030" and theme.colors["groove"] == "#000000"
    assert depth.depth_colors(theme.colors)["tray_top"] == "#102030"
    assert themes.export_dict(theme)["colors"]["tray_top"] == "#102030"
    plain = themes.export_dict(themes.BUILT_IN["dark"])["colors"]
    assert set(plain) == set(themes.TOKEN_NAMES)  # a theme without any keeps the same file format as before
