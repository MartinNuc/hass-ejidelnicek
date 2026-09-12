# Brand assets

Two consumers, two places:

* **HACS** checks `custom_components/ejidelnicek/brand/` inside this repo
  first, and only falls back to the brands repository. Those in-repo copies
  exist, so HACS shows the icon immediately — and its validation requires
  one or the other to be present.
* **Home Assistant's own integrations page** reads only the central
  [home-assistant/brands][brands] repository, via `brands.home-assistant.io`.
  Until these files are accepted there, that page shows the default
  placeholder icon — expected, not a fault in the install.

The two copies are identical; `brands/tools/` regenerates both.

## Files

| File | Size | Purpose |
| --- | --- | --- |
| `custom_integrations/ejidelnicek/icon.png` | 256×256 | square icon |
| `custom_integrations/ejidelnicek/icon@2x.png` | 512×512 | hDPI icon |
| `custom_integrations/ejidelnicek/logo.png` | 865×256 | horizontal wordmark |
| `custom_integrations/ejidelnicek/logo@2x.png` | 1730×512 | hDPI wordmark |

The directory layout above mirrors the brands repository exactly, so the
folder can be copied across as-is.

## Submitting

1. Fork [home-assistant/brands][brands].
2. Copy `custom_integrations/ejidelnicek/` into the fork's
   `custom_integrations/` directory.
3. Open a pull request. The repository's CI checks image dimensions,
   transparency and trimming; the files here are generated to satisfy those.

Custom integrations go under `custom_integrations/`, not `core_integrations/`.
The folder name must equal the integration's domain, `ejidelnicek`.

## Regenerating

The artwork is drawn programmatically rather than stored as a binary blob
nobody can edit, so it can be adjusted and rebuilt deterministically:

```bash
python brands/tools/generate_icon.py   # icon_256.png, icon_512.png
python brands/tools/generate_logo.py   # logo.png, logo@2x.png (needs icon_512.png)
```

Both need Pillow, which ships with the `dev` dependency group. Run them from
a scratch directory and copy the output over the files above.

`generate_logo.py` renders "E-jídelníček" in Avenir Next Demi Bold and
asserts up front that the font actually carries every glyph it needs. That
guard exists because the first attempt used Arial Rounded Bold, which
silently rendered `č` as a tofu box — the font reported a width for the
missing glyph, so a width check alone did not catch it.

## The design

A white bowl of soup with three rising plumes of steam, on a warm amber
gradient. Soup is the one component every E-jídelníček canteen publishes for
every serving day, which makes it the most representative single symbol for
the menus this integration reads.

[brands]: https://github.com/home-assistant/brands
