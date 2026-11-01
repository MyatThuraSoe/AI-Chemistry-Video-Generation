"""Deterministic scene layouts drawn with Pillow.

Every layout is authored on a 1280x720 grid and scaled at runtime. Layouts are
intentionally simple: one main idea per scene, large type, high contrast.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from app.generation.storyboard_builder import StoryboardScene
from app.generation.visuals.theme import (
    ACID,
    ACID_ORANGE,
    BASE,
    BORDER,
    CARD,
    CARD_LIGHT,
    DARK_BORDER,
    ELECTRON,
    MUTED,
    NEUTRAL,
    PRIMARY,
    PURPLE,
    TEXT,
    Canvas,
    draw_atom,
    draw_header,
    draw_heading,
    draw_label_row,
    draw_mini_scale,
    draw_ph_scale,
    draw_shared_pair,
    ease_out,
    mix,
    ph_color,
)

LayoutFunction = Callable[[Canvas, StoryboardScene, float, str], None]


def _labels(scene: StoryboardScene) -> list[str]:
    return [element.value for element in scene.elements if element.type == "text"]


def _appear(t: float, start: float, end: float) -> float:
    if end <= start:
        return 1.0 if t >= end else 0.0
    return ease_out((t - start) / (end - start))


def _label_or(labels: list[str], index: int, default: str) -> str:
    return labels[index] if index < len(labels) else default


def _title_motif(canvas: Canvas, concept_id: str, t: float) -> None:
    progress = _appear(t, 0.1, 0.8)
    if concept_id == "ph-scale":
        draw_mini_scale(canvas, 640, 486, width=780)
        for value in (2, 7, 9):
            x = 640 - 390 + 780 * value / 14
            canvas.circle(x, 486, 8, fill=ph_color(value), outline=TEXT, width=2)
        return
    if concept_id == "covalent-bonding":
        y = 480
        left_x = 640 - 120 * (1 - progress)
        right_x = 640 + 120 * (1 - progress)
        canvas.line(left_x + 46, y, right_x - 46, y, mix(PRIMARY, "#FFFFFF", 0.2), width=3)
        canvas.circle(left_x, y, 48, fill=mix("#4CC9F0", "#000000", 0.45), outline=PRIMARY, width=3)
        canvas.circle(
            right_x, y, 48, fill=mix("#90BE6D", "#000000", 0.45), outline=NEUTRAL, width=3
        )
        canvas.text(left_x, y + 1, "H", 30, TEXT, anchor="mm")
        canvas.text(right_x, y + 1, "H", 30, TEXT, anchor="mm")
        draw_shared_pair(canvas, 640, y, spread=15, progress=progress)
        return
    # Ionic vs covalent split motif.
    canvas.panel(360, 444, 620, 520, fill="#2A1620", outline=ACID, radius=18)
    canvas.panel(660, 444, 920, 520, fill="#0E2C3E", outline=PRIMARY, radius=18)
    canvas.text(490, 482, "ionic", 24, ACID, anchor="mm")
    canvas.text(790, 482, "covalent", 24, PRIMARY, anchor="mm")
    canvas.text(640, 482, "vs", 20, MUTED, anchor="mm")


def draw_title(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    labels = _labels(scene)
    title_size = 56.0
    title = scene.concept_title or scene.heading
    lines = canvas.wrap(title, title_size, 1080)

    y = 178.0
    line_height = 66.0
    for index, line in enumerate(lines[:2]):
        canvas.text(640, y + index * line_height, line, title_size, TEXT, anchor="ma", bold=True)
    title_bottom = y + len(lines[:2]) * line_height
    canvas.draw.rectangle(
        [canvas.x(600), canvas.y(title_bottom + 8), canvas.x(680), canvas.y(title_bottom + 12)],
        fill=PRIMARY,
    )
    canvas.wrapped_text(
        640,
        title_bottom + 28,
        scene.concept_summary,
        24,
        980,
        MUTED,
        anchor="ma",
        bold=False,
        max_lines=2,
    )
    _title_motif(canvas, concept_id, t)
    draw_label_row(canvas, labels, y=538, size=21)


def draw_ph_scale_overview(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.75)

    x1, x2, y = 120.0, 1160.0, 392.0
    canvas.panel(84, 214, 1196, 500, fill="#091A31", outline=BORDER, radius=30)
    for value, color in ((0, ph_color(0)), (7, ph_color(7)), (14, ph_color(14))):
        x = x1 + (x2 - x1) * value / 14
        canvas.text(x, 270, str(value), 54, color, anchor="ma")
        canvas.text(
            x,
            330,
            "acidic" if value == 0 else ("neutral" if value == 7 else "basic"),
            18,
            MUTED,
            anchor="ma",
        )
    draw_ph_scale(canvas, x1, x2, y, progress=progress, number_size=19, track_height=20)
    canvas.text(640, 448, "Most common values are between 0 and 14", 18, MUTED, anchor="ma")


def draw_ph_regions(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)
    regions = [
        (_label_or(labels, 0, "acidic"), "0 – 6.9", ACID, 90, 445, 0.0, 7.0),
        (_label_or(labels, 1, "neutral"), "7", NEUTRAL, 455, 825, 7.0, 7.0),
        (_label_or(labels, 2, "basic"), "7.1 – 14", BASE, 835, 1190, 7.0, 14.0),
    ]
    x1, x2, y = 120.0, 1160.0, 422.0
    draw_ph_scale(
        canvas, x1, x2, y, progress=_appear(t, 0.05, 0.6), number_size=18, track_height=20
    )

    for index, (label, range_text, color, left, right, start_ph, end_ph) in enumerate(regions):
        progress = _appear(t, 0.15 + index * 0.12, 0.65 + index * 0.12)
        offset = (1 - progress) * 24
        canvas.panel(
            left,
            214 + offset,
            right,
            340 + offset,
            fill=mix(color, "#07152A", 0.82),
            outline=color,
            radius=20,
            width=2,
        )
        canvas.text((left + right) / 2, 246 + offset, label, 27, color, anchor="ma", bold=True)
        canvas.text((left + right) / 2, 294 + offset, range_text, 20, TEXT, anchor="ma")
        tip = x1 + (x2 - x1) * ((start_ph + end_ph) / 2) / 14
        canvas.dashed_line(
            (left + right) / 2,
            344 + offset,
            tip,
            y - 14,
            mix(color, "#FFFFFF", 0.1),
            width=2,
            dash=7,
            gap=6,
        )
        canvas.circle(tip, y, 9, fill=color, outline=TEXT, width=2)


def draw_hydrogen_ions(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    canvas.panel(86, 200, 610, 505, fill="#24131C", outline=ACID, radius=28)
    canvas.panel(670, 200, 1194, 505, fill="#0E203B", outline=BASE, radius=28)
    canvas.text(348, 238, "Lower pH", 27, ACID, anchor="ma", bold=True)
    canvas.text(932, 238, "Higher pH", 27, BASE, anchor="ma", bold=True)
    canvas.text(348, 278, "more H⁺ ions", 19, MUTED, anchor="ma")
    canvas.text(932, 278, "fewer H⁺ ions", 19, MUTED, anchor="ma")

    many = _appear(t, 0.1, 0.65)
    few = _appear(t, 0.35, 0.9)
    positions_many = [
        (200, 350),
        (280, 320),
        (365, 340),
        (450, 315),
        (520, 355),
        (240, 425),
        (335, 410),
        (430, 430),
        (505, 405),
        (320, 475),
    ]
    for index, (x, y) in enumerate(positions_many):
        if index / len(positions_many) <= many:
            canvas.circle(x, y, 21, fill=mix(ACID, "#000000", 0.65), outline=ACID, width=2)
            canvas.text(x, y + 1, "H⁺", 14, TEXT, anchor="mm", bold=True)
    positions_few = [(760, 355), (900, 330), (1060, 380), (850, 440), (1010, 455)]
    for index, (x, y) in enumerate(positions_few):
        if index / len(positions_few) <= few:
            canvas.circle(x, y, 21, fill=mix(BASE, "#000000", 0.6), outline=BASE, width=2)
            canvas.text(x, y + 1, "H⁺", 14, TEXT, anchor="mm", bold=True)

    canvas.pill(810, 150, "pH depends on H⁺ concentration", 20, fill=CARD_LIGHT, outline=ELECTRON)


def draw_log_scale(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.6)
    canvas.panel(90, 205, 360, 455, fill="#0D2444", outline=BORDER, radius=26)
    canvas.text(225, 255, "1 pH step", 28, TEXT, anchor="ma", bold=True)
    canvas.text(225, 320, "each unit", 20, MUTED, anchor="ma")
    canvas.text(225, 356, "10×", 46, PRIMARY, anchor="ma", bold=True)

    canvas.panel(410, 205, 870, 455, fill="#201B12", outline=ELECTRON, radius=30)
    canvas.text(640, 268, "H⁺ concentration", 23, MUTED, anchor="ma")
    canvas.text(640, 355, "× 10", 102, ELECTRON, anchor="mm", bold=True)
    canvas.text(640, 420, "for every single unit", 20, TEXT, anchor="ma")

    canvas.panel(920, 205, 1190, 455, fill="#0D2444", outline=BORDER, radius=26)
    canvas.text(1055, 246, "H⁺ ion count", 21, MUTED, anchor="ma")
    for index in range(10):
        col = index % 5
        row = index // 5
        color = ELECTRON if index < int(progress * 10 + 0.99) else "#2A3F59"
        canvas.circle(985 + col * 35, 310 + row * 42, 9, fill=color)
    canvas.text(1055, 410, "1 → 10 → 100", 17, MUTED, anchor="ma")

    draw_mini_scale(canvas, 640, 498, width=620)


def draw_examples_on_scale(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)

    examples = [
        (_label_or(labels, 0, "lemon juice"), 2.0, "#F9C74F", "lemon", "acidic"),
        (_label_or(labels, 1, "water"), 7.0, PRIMARY, "water", "neutral"),
        (_label_or(labels, 2, "soap"), 9.0, PURPLE, "soap", "basic"),
    ]

    card_width, card_height = 330.0, 126.0
    card_centers = (260.0, 640.0, 1020.0)
    for index, (label, ph, color, icon, region) in enumerate(examples):
        progress = _appear(t, 0.18 + index * 0.12, 0.68 + index * 0.12)
        cx = card_centers[index]
        top = 182 + (1 - progress) * 26
        canvas.panel(
            cx - card_width / 2,
            top,
            cx + card_width / 2,
            top + card_height,
            fill=mix(color, "#07152A", 0.86),
            outline=color,
            radius=22,
        )

        icon_x, icon_y = cx - 112, top + 63
        canvas.circle(icon_x, icon_y, 30, fill=mix(color, "#07152A", 0.55), outline=color, width=3)
        if icon == "lemon":
            canvas.circle(icon_x, icon_y, 16, fill=color)
            canvas.line(icon_x + 10, icon_y - 12, icon_x + 19, icon_y - 21, NEUTRAL, width=4)
        elif icon == "water":
            canvas.draw.polygon(
                [
                    (canvas.x(icon_x), canvas.y(icon_y - 20)),
                    (canvas.x(icon_x - 16), canvas.y(icon_y + 5)),
                    (canvas.x(icon_x + 16), canvas.y(icon_y + 5)),
                ],
                fill=color,
            )
            canvas.circle(icon_x, icon_y + 4, 16, fill=color)
        else:
            canvas.circle(
                icon_x, icon_y, 16, fill=mix(color, "#FFFFFF", 0.25), outline=color, width=2
            )
            canvas.circle(icon_x - 5, icon_y - 5, 3, fill=TEXT)

        canvas.text(cx - 70, top + 34, label, 23, TEXT, bold=True)
        canvas.text(cx - 70, top + 74, region, 18, color, bold=True)
        canvas.text(cx + 140, top + 28, "pH", 15, MUTED, anchor="rm")
        canvas.text(cx + 140, top + 66, f"{ph:g}", 46, color, anchor="rm", bold=True)

    x1, x2, y = 140.0, 1140.0, 430.0
    canvas.panel(84, 356, 1196, 516, fill="#091A31", outline=BORDER, radius=28)
    draw_ph_scale(
        canvas, x1, x2, y, progress=_appear(t, 0.05, 0.65), number_size=18, track_height=20
    )
    for index, (_, ph, color, _, _) in enumerate(examples):
        progress = _appear(t, 0.25 + index * 0.12, 0.7 + index * 0.12)
        if progress <= 0:
            continue
        x = x1 + (x2 - x1) * ph / 14
        canvas.circle(x, y, 11, fill=color, outline=TEXT, width=3)


def draw_recap_list(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    labels = _labels(scene)
    is_ph = concept_id == "ph-scale"
    if is_ph:
        defaults = ["below 7 acidic", "7 neutral", "above 7 basic"]
        values = [_label_or(labels, index, defaults[index]) for index in range(3)]
    else:
        values = (labels or ["share electrons", "more stable"])[:4]

    draw_heading(canvas, scene.heading)
    colors = [ACID, NEUTRAL, BASE]
    for index, value in enumerate(values):
        progress = _appear(t, 0.1 + index * 0.12, 0.55 + index * 0.12)
        offset = (1 - progress) * 30
        top = 188 + index * 86 + offset
        canvas.panel(90, top, 1190, top + 70, fill=CARD, outline=colors[index % 3], radius=18)
        canvas.circle(
            136,
            top + 35,
            21,
            fill=mix(colors[index % 3], "#07152A", 0.4),
            outline=colors[index % 3],
            width=2,
        )
        canvas.check(136, top + 35, 12, TEXT)
        canvas.text(180, top + 20, value, 24, TEXT, bold=True)

    if is_ph:
        draw_mini_scale(canvas, 640, 505, width=640)
        canvas.text(640, 538, "pH 0 → 7 → 14", 15, MUTED, anchor="ma")
    else:
        canvas.panel(440, 430, 840, 562, fill=CARD, outline=ELECTRON, radius=26)
        draw_atom(canvas, 520, 492, 38, symbol="H", color=PRIMARY, electrons=1)
        draw_atom(canvas, 760, 492, 38, symbol="H", color=PRIMARY, electrons=1)
        draw_shared_pair(canvas, 640, 492, spread=12)
        canvas.text(640, 536, "shared electron pair", 15, ELECTRON, anchor="ma")


def draw_valence_electrons(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.8)
    cx, cy, radius = 490, 370, 138
    draw_atom(
        canvas,
        cx,
        cy,
        radius,
        symbol="C",
        color=PRIMARY,
        electrons=6,
        highlight_outer=True,
        progress=progress,
    )
    canvas.ring(cx, cy, radius * 0.5, color=mix(NEUTRAL, "#FFFFFF", 0.15), width=2)
    for index in range(2):
        angle = math.pi * index + progress
        canvas.circle(
            cx + radius * 0.5 * math.cos(angle),
            cy + radius * 0.5 * math.sin(angle),
            7,
            fill=ELECTRON,
        )

    canvas.panel(760, 226, 1160, 300, fill=CARD_LIGHT, outline=PRIMARY, radius=18)
    canvas.text(790, 244, "outer shell", 21, PRIMARY, bold=True)
    canvas.text(790, 272, "the highest-energy electrons", 16, MUTED, bold=False)
    canvas.dashed_line(760, 264, cx + radius, cy - radius * 0.25, PRIMARY, width=2, dash=8, gap=6)

    canvas.panel(760, 330, 1160, 430, fill="#1E1A0E", outline=ELECTRON, radius=18)
    canvas.text(790, 350, "valence electrons", 23, ELECTRON, bold=True)
    canvas.text(790, 384, "electrons available for bonding", 16, MUTED, bold=False)
    canvas.dashed_line(
        760, 380, cx + radius * 0.72, cy + radius * 0.42, ELECTRON, width=2, dash=8, gap=6
    )


def draw_electron_sharing(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.7)
    left_x = 290 + 140 * progress
    right_x = 990 - 140 * progress
    y = 372
    canvas.dashed_line(
        left_x + 92, y, right_x - 92, y, mix(PRIMARY, "#FFFFFF", 0.1), width=2, dash=9, gap=7
    )
    draw_atom(canvas, left_x, y, 100, symbol="C", color=PRIMARY, electrons=4, progress=progress)
    draw_atom(canvas, right_x, y, 100, symbol="O", color=NEUTRAL, electrons=4, progress=progress)
    pair_progress = _appear(t, 0.35, 0.85)
    if pair_progress > 0:
        canvas.circle(640, y, 42, fill=mix(ELECTRON, "#07152A", 0.75), outline=ELECTRON, width=2)
        draw_shared_pair(canvas, 640, y, spread=16, progress=pair_progress)
        canvas.text(640, y + 66, "shared pair", 18, ELECTRON, anchor="ma")
    canvas.pill(470, 200, "valence electrons", 19, fill=CARD_LIGHT, outline=PRIMARY)


def draw_nonmetal_sharing(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.75)
    left_x, right_x, y = 390, 890, 355
    canvas.panel(
        160, 188, 620, 500, fill="#0C2733", outline=mix(PRIMARY, "#FFFFFF", 0.1), radius=26
    )
    canvas.panel(660, 188, 1120, 500, fill="#112A1B", outline=NEUTRAL, radius=26)
    draw_atom(canvas, left_x, y, 104, symbol="N", color=PRIMARY, electrons=5, progress=progress)
    draw_atom(canvas, right_x, y, 104, symbol="O", color=NEUTRAL, electrons=6, progress=progress)
    canvas.text(left_x, 474, "nonmetal atom", 19, PRIMARY, anchor="ma")
    canvas.text(right_x, 474, "nonmetal atom", 19, NEUTRAL, anchor="ma")
    canvas.line(left_x + 104, y, right_x - 104, y, mix(TEXT, "#07152A", 0.5), width=3)
    draw_shared_pair(canvas, 640, y, spread=15, progress=_appear(t, 0.35, 0.9))
    canvas.pill(800, 150, "both are nonmetals", 18, fill=CARD_LIGHT, outline=NEUTRAL)


def draw_h2_molecule(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.7)
    left_x = 410 + 80 * progress
    right_x = 870 - 80 * progress
    y = 345
    draw_atom(canvas, left_x, y, 92, symbol="H", color=PRIMARY, electrons=1, progress=progress)
    draw_atom(canvas, right_x, y, 92, symbol="H", color=PRIMARY, electrons=1, progress=progress)
    canvas.dashed_line(
        left_x + 82, y, right_x - 82, y, mix(ELECTRON, "#FFFFFF", 0.2), width=2, dash=8, gap=6
    )
    draw_shared_pair(canvas, 640, y, spread=16, progress=_appear(t, 0.35, 0.9))

    canvas.panel(540, 446, 740, 545, fill="#201B12", outline=ELECTRON, radius=20)
    canvas.text(640, 458, "H₂", 42, ELECTRON, anchor="ma", bold=True)
    canvas.text(640, 518, "hydrogen molecule", 14, MUTED, anchor="ma")


def draw_shared_attraction(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.7)
    left_x, right_x, y = 370, 910, 385
    canvas.circle(left_x, y, 82, fill=mix(PRIMARY, "#07152A", 0.55), outline=PRIMARY, width=3)
    canvas.circle(right_x, y, 82, fill=mix(NEUTRAL, "#07152A", 0.55), outline=NEUTRAL, width=3)
    canvas.text(left_x, y + 1, "H", 36, TEXT, anchor="mm", bold=True)
    canvas.text(right_x, y + 1, "H", 36, TEXT, anchor="mm", bold=True)
    canvas.text(left_x, y + 104, "nucleus", 18, MUTED, anchor="ma")
    canvas.text(right_x, y + 104, "nucleus", 18, MUTED, anchor="ma")

    draw_shared_pair(canvas, 640, y, spread=18, progress=_appear(t, 0.25, 0.85))

    canvas.arrow(left_x + 95, y - 12, 590, y - 12, ELECTRON, width=3, head=11, progress=progress)
    canvas.arrow(right_x - 95, y + 12, 690, y + 12, ELECTRON, width=3, head=11, progress=progress)
    canvas.pill(560, 280, "shared pair", 19, fill=CARD_LIGHT, outline=ELECTRON)
    canvas.text(640, 460, "attracted to both nuclei", 20, TEXT, anchor="ma")


def draw_ionic_transfer(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.08, 0.8)
    left_x, right_x, y = 330, 950, 380
    canvas.panel(120, 190, 590, 520, fill="#251620", outline=ACID, radius=28)
    canvas.panel(690, 190, 1160, 520, fill="#0D2733", outline=PRIMARY, radius=28)
    draw_atom(
        canvas, left_x, y, 112, symbol="Na", color=ACID_ORANGE, electrons=2, progress=progress
    )
    draw_atom(canvas, right_x, y, 112, symbol="Cl", color=PRIMARY, electrons=4, progress=progress)

    start_x, end_x = left_x + 70, right_x - 160
    arc_x = start_x + (end_x - start_x) * progress
    arc_y = y - 150 * math.sin(math.pi * progress)
    canvas.dashed_line(start_x, y - 60, arc_x, arc_y, ELECTRON, width=2, dash=8, gap=6)
    canvas.circle(arc_x, arc_y, 13, fill=ELECTRON, outline="#FFF3C4", width=2)
    canvas.text(arc_x, arc_y - 30, "e⁻", 17, ELECTRON, anchor="ma", bold=True)
    canvas.arrow(
        left_x + 145, 268, right_x - 145, 268, ELECTRON, width=2, head=10, progress=progress
    )
    canvas.text(left_x, 537, "loses an electron", 19, MUTED, anchor="ma")
    canvas.text(right_x, 537, "gains an electron", 19, MUTED, anchor="ma")


def draw_metal_nonmetal(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.7)
    canvas.panel(90, 196, 570, 500, fill="#1B1828", outline=ACID_ORANGE, radius=28)
    canvas.panel(710, 196, 1190, 500, fill="#0D2733", outline=PRIMARY, radius=28)
    draw_atom(canvas, 330, 330, 104, symbol="Na", color=ACID_ORANGE, electrons=2, progress=progress)
    draw_atom(canvas, 970, 330, 104, symbol="Cl", color=PRIMARY, electrons=4, progress=progress)
    canvas.text(330, 458, _label_or(labels, 0, "metal"), 27, ACID_ORANGE, anchor="ma", bold=True)
    canvas.text(970, 458, _label_or(labels, 1, "nonmetal"), 27, PRIMARY, anchor="ma", bold=True)
    canvas.arrow(600, 340, 680, 340, ELECTRON, width=4, head=13, progress=progress)
    canvas.circle(600 + 80 * progress, 340, 12, fill=ELECTRON, outline="#FFF3C4", width=2)
    canvas.text(640, 380, "often", 16, MUTED, anchor="ma")
    canvas.pill(500, 150, "electron transfer", 19, fill=CARD_LIGHT, outline=ELECTRON)


def draw_ionic_ions(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.7)
    left_x = 330 + 70 * progress
    right_x = 950 - 70 * progress
    y = 370
    canvas.circle(left_x, y, 105, fill=mix(ACID, "#07152A", 0.55), outline=ACID, width=3)
    canvas.circle(right_x, y, 105, fill=mix(PRIMARY, "#07152A", 0.55), outline=PRIMARY, width=3)
    canvas.text(left_x, y + 1, "Na⁺", 35, TEXT, anchor="mm", bold=True)
    canvas.text(right_x, y + 1, "Cl⁻", 35, TEXT, anchor="mm", bold=True)
    canvas.circle(left_x + 80, y - 72, 20, fill=ACID, outline=TEXT, width=2)
    canvas.text(left_x + 80, y - 71, "+", 24, TEXT, anchor="mm", bold=True)
    canvas.circle(right_x - 80, y - 72, 20, fill=PRIMARY, outline=TEXT, width=2)
    canvas.text(right_x - 80, y - 71, "−", 24, TEXT, anchor="mm", bold=True)
    canvas.arrow(
        left_x + 135, y - 22, right_x - 135, y - 22, ELECTRON, width=3, head=12, progress=progress
    )
    canvas.arrow(
        right_x - 135,
        y + 22,
        left_x + 135,
        y + 22,
        ELECTRON,
        width=3,
        head=12,
        progress=_appear(t, 0.25, 0.85),
    )
    canvas.pill(520, 186, "opposite charges attract", 19, fill=CARD_LIGHT, outline=ELECTRON)
    canvas.text(left_x, 500, _label_or(labels, 0, "positive ion"), 20, ACID, anchor="ma")
    canvas.text(right_x, 500, _label_or(labels, 1, "negative ion"), 20, PRIMARY, anchor="ma")


def draw_salt_example(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.75)
    canvas.panel(110, 200, 660, 505, fill="#0B1B31", outline=BORDER, radius=28)
    start_x, start_y, gap = 295, 255, 90
    for row in range(3):
        for col in range(3):
            index = row * 3 + col
            if index / 9 > progress:
                continue
            x = start_x + col * gap
            y = start_y + row * gap
            positive = (row + col) % 2 == 0
            color = ACID if positive else PRIMARY
            canvas.circle(x, y, 31, fill=mix(color, "#07152A", 0.45), outline=color, width=2)
            canvas.text(x, y + 1, "+" if positive else "−", 26, TEXT, anchor="mm", bold=True)
    canvas.text(385, 472, "ionic lattice", 17, MUTED, anchor="ma")

    canvas.panel(730, 224, 1170, 480, fill="#201B12", outline=ELECTRON, radius=28)
    canvas.text(950, 270, _label_or(labels, 0, "NaCl"), 82, ELECTRON, anchor="ma", bold=True)
    canvas.text(950, 366, _label_or(labels, 1, "table salt"), 28, TEXT, anchor="ma", bold=True)
    canvas.text(950, 420, "a common ionic compound", 18, MUTED, anchor="ma")


def draw_covalent_share(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.7)
    canvas.panel(120, 190, 590, 265, fill="#251620", outline=ACID, radius=18)
    canvas.panel(690, 190, 1160, 265, fill="#0E2C3E", outline=PRIMARY, radius=18)
    canvas.text(355, 226, "ionic: transfer", 24, ACID, anchor="mm", bold=True)
    canvas.text(925, 226, "covalent: share", 24, PRIMARY, anchor="mm", bold=True)

    left_x, right_x, y = 470, 810, 392
    canvas.dashed_line(
        left_x + 78, y, right_x - 78, y, mix(ELECTRON, "#FFFFFF", 0.15), width=2, dash=8, gap=6
    )
    draw_atom(canvas, left_x, y, 88, symbol="C", color=PRIMARY, electrons=4, progress=progress)
    draw_atom(canvas, right_x, y, 88, symbol="O", color=NEUTRAL, electrons=4, progress=progress)
    draw_shared_pair(canvas, 640, y, spread=16, progress=_appear(t, 0.3, 0.85))
    canvas.text(640, 500, "atoms share electron pairs", 20, TEXT, anchor="ma")
    draw_label_row(canvas, labels, y=532, size=19)


def draw_molecule_example(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)
    progress = _appear(t, 0.05, 0.7)
    ox, oy = 620, 345
    h1 = (470, 455)
    h2 = (780, 455)
    canvas.line(ox - 55, oy + 55, h1[0] + 30, h1[1] - 30, mix(PRIMARY, "#FFFFFF", 0.2), width=4)
    canvas.line(ox + 55, oy + 55, h2[0] - 30, h2[1] - 30, mix(PRIMARY, "#FFFFFF", 0.2), width=4)
    canvas.circle(ox, oy, 82, fill=mix(ACID_ORANGE, "#07152A", 0.55), outline=ACID_ORANGE, width=3)
    canvas.text(ox, oy + 1, "O", 42, TEXT, anchor="mm", bold=True)
    canvas.circle(h1[0], h1[1], 48, fill=mix(PRIMARY, "#07152A", 0.5), outline=PRIMARY, width=3)
    canvas.circle(h2[0], h2[1], 48, fill=mix(PRIMARY, "#07152A", 0.5), outline=PRIMARY, width=3)
    canvas.text(h1[0], h1[1] + 1, "H", 28, TEXT, anchor="mm", bold=True)
    canvas.text(h2[0], h2[1] + 1, "H", 28, TEXT, anchor="mm", bold=True)

    for fraction in (0.38, 0.62):
        sx = ox + (h1[0] - ox) * fraction
        sy = oy + (h1[1] - oy) * fraction
        tx = ox + (h2[0] - ox) * fraction
        ty = oy + (h2[1] - oy) * fraction
        if progress > 0.4:
            canvas.circle(sx, sy, 8, fill=ELECTRON)
            canvas.circle(tx, ty, 8, fill=ELECTRON)

    canvas.panel(1000, 236, 1180, 356, fill="#201B12", outline=ELECTRON, radius=22)
    canvas.text(1090, 270, _label_or(labels, 0, "H2O"), 48, ELECTRON, anchor="ma", bold=True)
    canvas.text(1090, 325, "water", 18, MUTED, anchor="ma")
    canvas.pill(900, 430, "covalent molecule", 19, fill=CARD_LIGHT, outline=PRIMARY)


def draw_comparison_table(
    canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str
) -> None:
    del concept_id
    draw_heading(canvas, scene.heading)
    left, right = 90.0, 1190.0
    split = 640.0
    top, header_h, row_h = 180.0, 66.0, 82.0
    canvas.panel(left, top, right, top + header_h, fill=CARD, outline=BORDER, radius=18)
    canvas.text((left + split) / 2, top + header_h / 2, "Ionic", 28, ACID, anchor="mm", bold=True)
    canvas.text(
        (split + right) / 2, top + header_h / 2, "Covalent", 28, PRIMARY, anchor="mm", bold=True
    )
    canvas.line(split, top + 8, split, top + header_h + row_h * 3, DARK_BORDER, width=2)

    rows = [
        ("transfers electrons", "shares electrons"),
        ("forms ions", "forms molecules"),
        ("metal + nonmetal (often)", "nonmetals (often)"),
    ]
    for index, (ionic_text, covalent_text) in enumerate(rows):
        progress = _appear(t, 0.12 + index * 0.12, 0.55 + index * 0.12)
        y1 = top + header_h + index * row_h
        y2 = y1 + row_h
        fill = "#0A1B32" if index % 2 == 0 else CARD
        canvas.panel(left, y1, right, y2, fill=fill, outline=DARK_BORDER, radius=0, width=1)
        offset = (1 - progress) * 16
        canvas.text(
            (left + split) / 2,
            y1 + row_h / 2 + offset,
            ionic_text,
            21,
            TEXT,
            anchor="mm",
            bold=False,
        )
        canvas.text(
            (split + right) / 2,
            y1 + row_h / 2 + offset,
            covalent_text,
            21,
            TEXT,
            anchor="mm",
            bold=False,
        )
    canvas.text(365, 500, "transfer", 19, ACID, anchor="ma", bold=True)
    canvas.text(915, 500, "share", 19, PRIMARY, anchor="ma", bold=True)


def draw_generic(canvas: Canvas, scene: StoryboardScene, t: float, concept_id: str) -> None:
    del concept_id
    labels = _labels(scene)
    draw_heading(canvas, scene.heading)
    colors = [PRIMARY, NEUTRAL, ELECTRON, PURPLE]
    for index, label in enumerate(labels[:4]):
        progress = _appear(t, 0.1 + index * 0.1, 0.55 + index * 0.1)
        col = index % 2
        row = index // 2
        left = 90 + col * 560
        top = 196 + row * 150 + (1 - progress) * 20
        canvas.panel(left, top, left + 540, top + 122, fill=CARD, outline=colors[index], radius=22)
        canvas.circle(
            left + 52,
            top + 61,
            23,
            fill=mix(colors[index], "#07152A", 0.35),
            outline=colors[index],
            width=2,
        )
        canvas.text(left + 92, top + 34, label, 25, TEXT, bold=True)
    canvas.wrapped_text(
        640,
        500,
        scene.visual_description,
        18,
        1040,
        MUTED,
        anchor="ma",
        bold=False,
        max_lines=2,
    )


LAYOUTS: dict[str, LayoutFunction] = {
    "title": draw_title,
    "ph_scale_overview": draw_ph_scale_overview,
    "ph_regions": draw_ph_regions,
    "hydrogen_ions": draw_hydrogen_ions,
    "log_scale": draw_log_scale,
    "examples_on_scale": draw_examples_on_scale,
    "recap_list": draw_recap_list,
    "valence_electrons": draw_valence_electrons,
    "electron_sharing": draw_electron_sharing,
    "nonmetal_sharing": draw_nonmetal_sharing,
    "h2_molecule": draw_h2_molecule,
    "shared_attraction": draw_shared_attraction,
    "ionic_transfer": draw_ionic_transfer,
    "metal_nonmetal": draw_metal_nonmetal,
    "ionic_ions": draw_ionic_ions,
    "salt_example": draw_salt_example,
    "covalent_share": draw_covalent_share,
    "molecule_example": draw_molecule_example,
    "comparison_table": draw_comparison_table,
}


def draw_scene_layout(
    canvas: Canvas,
    scene: StoryboardScene,
    t: float,
    concept_id: str,
) -> None:
    function = LAYOUTS.get(scene.layout, draw_generic)
    function(canvas, scene, t, concept_id)


def draw_scene_frame(
    background: object,
    fonts: object,
    scene: StoryboardScene,
    concept_id: str,
    concept_title: str,
    scene_index: int,
    total_scenes: int,
    t: float,
) -> object:
    """Compatibility wrapper used by the renderer and thumbnail generator."""
    from PIL import Image

    from app.generation.visuals.theme import FontManager

    assert isinstance(background, Image.Image)
    assert isinstance(fonts, FontManager)
    image = background.copy()
    canvas = Canvas(image, fonts)
    draw_header(canvas, concept_title, scene_index, total_scenes)
    draw_scene_layout(canvas, scene, t, concept_id)
    from app.generation.visuals.theme import draw_caption

    draw_caption(canvas, scene.caption_text)
    return image
