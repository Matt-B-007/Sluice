# Sluice theme pack

Twenty-one colour themes for [Sluice](https://github.com/Matt-B-007/Sluice) 0.9.2 or newer, all updated for the 0.10.0 look (the previews show it). A picture of each is in
the `previews` folder (same name as the theme file).

Sluice also has seven themes built in (Dark, Light, High contrast, Retro Purple, Midnight Blue, Amber Console and Paper), so
those are not repeated here. The themes here need importing.

0.11.5 trimmed the pack from thirty: the copies of the built-in themes went, and so did six that looked almost the same as another
one (Cassette, Sepia Reader, Studio Slate, Vintage Hi-Fi, Halloween and Ocean). If you imported one of those, it stays in your themes
folder and keeps working; Paper, Sunset, Amber Console and Midnight Blue are the closest ones still here or built in.

## The themes

**Dark**
- Aurora: near-black with green and violet
- Blueprint: engineering-drawing blue with cyan lines
- Frost: cool blue-grey
- Forest: soft greens on deep green-grey
- Desert: sand-brown with turquoise
- Sunset: plum with orange and coral
- Rose: dark plum with pink
- Vampire: purple-grey with violet and pink
- Streamer Purple: deep purple with a bright violet accent
- Synthwave: indigo with pink and cyan
- Neon Tokyo: black with magenta and electric blue
- Retro Warm: warm retro browns and yellow
- Terminal Green: black with phosphor-green text
- Handheld Green: four-shades-of-olive handheld look
- OLED Black: true black panels with thin borders
- Night Mode: very dim and warm, for late nights
- Colour-blind friendly: blue and orange accents instead of red and green

**Light**
- Lavender Fog: soft purple-grey
- Mint Studio: pale green-white with teal
- Winter: ice blue and white
- Spring: soft green with pink

## How to use one

1. Download the `.json` file you want (on GitHub: open it, then the download button).
2. In Sluice, open **View > Theme > Import theme...** and pick the file.
3. It switches right away. To change, use **View > Theme** and pick another.

Imported themes are kept in Sluice's themes folder (**File > Open folder > Themes**), and Sluice shows up to 40
of them in the menu. **Remove an imported theme** deletes one.

## Good to know

- 0.10.0 added 13 colours (`surface2`, `border2`, `text2`, `track`, `meter_bg`, `accent_bg`, `accent_text`, `mute_bg`, `mute_fg`,
  `live_bg`, `live_fg`, `dashed`, `focus`). The files here list all of them. A theme file that leaves them out still works: Sluice works
  them out from the colours the file does give.

- 0.11.5 works out the colours that give depth (raised keys, glass, shadows, grooves and trays) from each theme's own colours, so a theme
  file does not need them. To set them by hand, add any of these to `colors`: `key_top`, `key_bottom` (a key's face, top and bottom),
  `key_skirt`, `key_rim` (its thick lower edge and the dark line under it), `key_edge`, `tray_top`, `tray_bottom`, `tray_lip`, `groove`,
  `shadow` (the shadow's colour), `knob_top`, `knob_bottom`, `knob_ring` and `outline` (Nexus's card outline).
- A theme only changes colours. It cannot change anything else in Sluice.
- The level meters' green-to-red colours, the Mute red and the Limiter teal are the same in every theme, so they
  always mean the same thing. That also means the meters keep their red-green colours in the colour-blind
  friendly theme; its accents, faders and highlights use blue and orange.
- In Handheld Green and Terminal Green the green meters sit close to the green panels. They still read, but the
  meters stand out more in the other themes.
- Every theme here passes Sluice's readability check, so Sluice will not warn you when you import one.

## Make your own

Use **View > Theme > Export current theme...** to save the theme you are using, edit the colours in any text
editor (`#rrggbb`), and import it. Share yours in the Discord.
