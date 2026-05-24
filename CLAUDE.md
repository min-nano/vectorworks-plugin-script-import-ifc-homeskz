# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A single-file VectorWorks plugin script (`main.py`) that imports IFC (Industry Foundation Classes) structural grid data and draws it as grid axis objects inside VectorWorks. The target use case is Japanese architectural projects (通り芯 = structural reference grid lines).

## Running the Script

This script is not a standalone Python program. It must be executed **inside VectorWorks** as a plugin script. The `vs` module is VectorWorks' proprietary Python scripting API — it is not pip-installable and has no stub package.

There is no build step, no test suite, and no linter configuration in this repository.

## How the Script Works

The single function `import_ifc_grid_with_layers_and_classes()` executes in five phases:

1. **File selection** — `vs.GetFileN()` opens a native file dialog; the user picks an `.ifc` file.
2. **IFC parsing** — The file is read as plain text. All newlines are stripped and statements are split on `;`. Three regex patterns extract:
   - `IFCCARTESIANPOINT` → `points` dict (id → (x, y))
   - `IFCPOLYLINE` → `polylines` dict (id → list of point ids)
   - `IFCGRIDAXIS` → `grid_axes` dict (id → {name, poly_id})
3. **Line resolution** — Each `IFCGRIDAXIS` is resolved through its `IFCPOLYLINE` to its endpoint coordinates. Duplicate lines (same geometry regardless of direction) are deduplicated via a sorted-tuple key. The bounding box center is computed for coordinate centering.
4. **Coordinate centering** — All coordinates are offset by `(center_x, center_y)` so the drawing lands near the VectorWorks origin.
5. **Drawing** — For each line, a `GridAxis` custom object is created in VectorWorks using `vs.CreateCustomObjectPath()`. If creation fails, a plain line is drawn as a fallback.

## VectorWorks Layer and Class Conventions

- **Layer**: All objects are placed on the `共通` (Common) layer. If this layer doesn't exist, the script creates it.
- **Classes** (X vs Y axis determination):
  - Name starts with `X` (case-insensitive) → class `01作図-01線-01基準線-01通り芯-X通り`
  - Name starts with `Y` (case-insensitive) → class `01作図-01線-01基準線-01通り芯-Y通り`
  - Otherwise: a near-vertical line (`|Δx| < |Δy|`) is treated as X, near-horizontal as Y
- **GridAxis record fields set**: `Label` (the axis name from IFC), `ShowBubbleAt` = `"Start Point"`

## Key Constraint: Regex-based IFC Parsing

The script does **not** use a dedicated IFC parser (e.g., `ifcopenshell`). It relies on regex over the raw STEP-format text. This means:

- Multi-line IFC statements are handled by stripping all newlines first.
- Only `IFCCARTESIANPOINT`, `IFCPOLYLINE`, and `IFCGRIDAXIS` entity types are extracted; all other IFC geometry is ignored.
- The regex for `IFCCARTESIANPOINT` only captures the first two coordinates (x, y); Z is ignored.
- If the IFC file uses non-UTF-8 encoding, the `open(..., encoding='utf-8')` call will raise an exception caught by the outer `try/except`.
