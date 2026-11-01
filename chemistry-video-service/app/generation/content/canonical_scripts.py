"""Curated, deterministic content packs for the three required concepts.

Adding a concept
----------------
1. Add a :class:`ConceptPack` below (or in a new content module).
2. Register it in ``app.generation.content.load_concept_packs``.
3. Add a renderer layout in ``app.generation.visuals.layouts`` (unknown layouts
   fall back to a generic label-card layout).
4. Add unit tests for aliases, required terms and duration validation.
"""

from __future__ import annotations

from app.domain.script import ConceptPack, Script, ScriptScene

CONTENT_VERSION = "2026.10.1"

PH_SCALE = ConceptPack(
    concept_id="ph-scale",
    aliases=[
        "how does the ph scale work",
        "how does the ph scale work?",
        "ph scale",
        "explain the ph scale",
        "what is the ph scale",
        "how does ph work",
        "explain how the ph scale works",
        "ph scale explained",
    ],
    required_terms=["pH", "acid", "basic", "neutral", "hydrogen"],
    min_duration_seconds=55,
    max_duration_seconds=75,
    content_version=CONTENT_VERSION,
    script=Script(
        concept_id="ph-scale",
        title="How the pH Scale Works",
        summary="The pH scale shows whether a solution is acidic, neutral, or basic.",
        target_duration_seconds=65,
        scenes=[
            ScriptScene(
                scene_id=1,
                layout="title",
                narration="The pH scale tells us whether a solution is acidic, neutral, or basic.",
                visual_description="Title card with the pH scale appearing in the background.",
                on_screen_labels=["pH scale"],
            ),
            ScriptScene(
                scene_id=2,
                layout="ph_scale_overview",
                narration="Most common pH values run from zero to fourteen.",
                visual_description=(
                    "Horizontal scale from 0 to 14 with numbers appearing sequentially."
                ),
                on_screen_labels=["0", "7", "14"],
            ),
            ScriptScene(
                scene_id=3,
                layout="ph_regions",
                narration=(
                    "A pH below seven is acidic. A pH of seven is neutral. "
                    "A pH above seven is basic, also called alkaline."
                ),
                visual_description=(
                    "The scale is divided into three colored regions: acidic, neutral, basic."
                ),
                on_screen_labels=["acidic", "neutral", "basic"],
            ),
            ScriptScene(
                scene_id=4,
                layout="hydrogen_ions",
                narration=(
                    "The scale is related to hydrogen ions. More hydrogen ions means lower pH. "
                    "Fewer hydrogen ions means higher pH."
                ),
                visual_description=(
                    "Icons of hydrogen ions appear on the acidic side, then fade on the basic side."
                ),
                on_screen_labels=["hydrogen ions", "lower pH", "higher pH"],
            ),
            ScriptScene(
                scene_id=5,
                layout="log_scale",
                narration=(
                    "Each step of one pH unit represents a tenfold change in hydrogen ion "
                    "concentration."
                ),
                visual_description=(
                    "One step on the scale highlights and shows a multiplication symbol."
                ),
                on_screen_labels=["1 pH step", "10 times change"],
            ),
            ScriptScene(
                scene_id=6,
                layout="examples_on_scale",
                narration=(
                    "Lemon juice is acidic, pure water is near neutral, and soapy water is basic."
                ),
                visual_description=(
                    "Three examples appear on the scale: lemon juice, water, soap."
                ),
                on_screen_labels=["lemon juice", "water", "soap"],
            ),
            ScriptScene(
                scene_id=7,
                layout="recap_list",
                narration=(
                    "Remember: below seven is acidic, seven is neutral, and above seven is basic."
                ),
                visual_description="Recap list with three bullet points and mini pH scale.",
                on_screen_labels=["below 7 acidic", "7 neutral", "above 7 basic"],
            ),
        ],
    ),
)

COVALENT_BONDING = ConceptPack(
    concept_id="covalent-bonding",
    aliases=[
        "why do atoms form covalent bonds",
        "why do atoms form covalent bonds?",
        "covalent bonding",
        "why covalent bonds form",
        "explain covalent bonding",
        "why atoms form covalent bonds",
        "how do covalent bonds form",
        "what is a covalent bond",
    ],
    required_terms=["atom", "electron", "share", "valence", "bond"],
    min_duration_seconds=55,
    max_duration_seconds=75,
    content_version=CONTENT_VERSION,
    script=Script(
        concept_id="covalent-bonding",
        title="Why Atoms Form Covalent Bonds",
        summary=(
            "Atoms form covalent bonds by sharing electrons to reach a more stable arrangement."
        ),
        target_duration_seconds=65,
        scenes=[
            ScriptScene(
                scene_id=1,
                layout="title",
                narration=(
                    "Atoms form bonds when they can reach a more stable arrangement of electrons."
                ),
                visual_description="Title card with two simple atoms moving closer together.",
                on_screen_labels=["covalent bonds"],
            ),
            ScriptScene(
                scene_id=2,
                layout="valence_electrons",
                narration=(
                    "The electrons in the outer shell are called valence electrons. "
                    "These are the electrons most involved in bonding."
                ),
                visual_description="A simple atom diagram highlights the outer shell electrons.",
                on_screen_labels=["outer shell", "valence electrons"],
            ),
            ScriptScene(
                scene_id=3,
                layout="electron_sharing",
                narration=(
                    "In a covalent bond, atoms share one or more pairs of valence electrons."
                ),
                visual_description=(
                    "Two atoms move closer and a shared electron pair appears between them."
                ),
                on_screen_labels=["shared electrons"],
            ),
            ScriptScene(
                scene_id=4,
                layout="nonmetal_sharing",
                narration=(
                    "This kind of sharing often happens between nonmetal atoms. "
                    "Nonmetals hold their electrons fairly tightly, so sharing is often "
                    "more favorable than transferring them completely."
                ),
                visual_description=(
                    "Two nonmetal atoms are shown with a subtle bond line between them."
                ),
                on_screen_labels=["nonmetal atoms"],
            ),
            ScriptScene(
                scene_id=5,
                layout="h2_molecule",
                narration=(
                    "For example, two hydrogen atoms can share electrons and form a hydrogen "
                    "molecule."
                ),
                visual_description="Two hydrogen atoms form H2 with a shared electron region.",
                on_screen_labels=["H", "H", "H2"],
            ),
            ScriptScene(
                scene_id=6,
                layout="shared_attraction",
                narration=(
                    "The shared electrons are attracted to both nuclei, helping hold the atoms "
                    "together. That shared attraction is what we call a covalent bond."
                ),
                visual_description=(
                    "Electron pair is highlighted between two nuclei with attraction arrows."
                ),
                on_screen_labels=["nuclei", "shared pair"],
            ),
            ScriptScene(
                scene_id=7,
                layout="recap_list",
                narration=(
                    "Covalent bonding means atoms share electron pairs to become more stable. "
                    "Sharing lets each atom count more electrons around itself, which is often "
                    "a more stable arrangement."
                ),
                visual_description="Recap list with a simple covalent bond icon.",
                on_screen_labels=["share electrons", "more stable"],
            ),
        ],
    ),
)

IONIC_VS_COVALENT = ConceptPack(
    concept_id="ionic-vs-covalent",
    aliases=[
        "what is the difference between ionic and covalent bonding",
        "what is the difference between ionic and covalent bonding?",
        "ionic vs covalent",
        "difference between ionic and covalent bonding",
        "compare ionic and covalent bonds",
        "ionic and covalent bonding",
        "ionic versus covalent",
        "ionic vs covalent bonding",
        "difference between ionic and covalent bonds",
    ],
    required_terms=["ionic", "covalent", "electron", "transfer", "share"],
    min_duration_seconds=65,
    max_duration_seconds=85,
    content_version=CONTENT_VERSION,
    script=Script(
        concept_id="ionic-vs-covalent",
        title="Ionic vs Covalent Bonding",
        summary=(
            "Ionic bonding involves electron transfer, while covalent bonding involves "
            "electron sharing."
        ),
        target_duration_seconds=75,
        scenes=[
            ScriptScene(
                scene_id=1,
                layout="title",
                narration=(
                    "Chemical bonds can form in different ways. Two major types are ionic and "
                    "covalent bonds."
                ),
                visual_description=(
                    "Title card with a split screen preview: left ionic, right covalent."
                ),
                on_screen_labels=["ionic", "covalent"],
            ),
            ScriptScene(
                scene_id=2,
                layout="ionic_transfer",
                narration=(
                    "In ionic bonding, one atom transfers one or more electrons to another atom. "
                    "The atom that loses electrons becomes positively charged, and the atom that "
                    "gains them becomes negatively charged."
                ),
                visual_description="An electron moves from one atom to another atom.",
                on_screen_labels=["electron transfer"],
            ),
            ScriptScene(
                scene_id=3,
                layout="metal_nonmetal",
                narration="This often happens between a metal and a nonmetal.",
                visual_description="Left side labels a metal atom and a nonmetal atom.",
                on_screen_labels=["metal", "nonmetal"],
            ),
            ScriptScene(
                scene_id=4,
                layout="ionic_ions",
                narration=(
                    "The electron transfer creates positive and negative ions, which attract "
                    "each other. Because opposite charges attract, the ions pack together in a "
                    "regular structure."
                ),
                visual_description="Atoms become plus and minus ions and move together.",
                on_screen_labels=["positive ion", "negative ion"],
            ),
            ScriptScene(
                scene_id=5,
                layout="salt_example",
                narration="Table salt, sodium chloride, is a common ionic compound.",
                visual_description="NaCl label appears near a simple ionic lattice icon.",
                on_screen_labels=["NaCl", "table salt"],
            ),
            ScriptScene(
                scene_id=6,
                layout="covalent_share",
                narration=(
                    "In covalent bonding, atoms share electron pairs instead of transferring them. "
                    "The shared pair belongs to both atoms at once, so neither atom takes full "
                    "ownership of the electrons."
                ),
                visual_description="Right side shows two atoms sharing electrons.",
                on_screen_labels=["shared electrons"],
            ),
            ScriptScene(
                scene_id=7,
                layout="molecule_example",
                narration=(
                    "Covalent bonds often form between nonmetal atoms, creating molecules such "
                    "as water."
                ),
                visual_description="Simple water molecule appears with covalent bonds.",
                on_screen_labels=["H2O"],
            ),
            ScriptScene(
                scene_id=8,
                layout="comparison_table",
                narration=(
                    "Ionic bonding transfers electrons and creates ions. Covalent bonding shares "
                    "electrons and forms molecules. The key difference is what happens to the "
                    "electrons: transfer creates ions, while sharing creates molecules."
                ),
                visual_description="Comparison table with two columns: ionic and covalent.",
                on_screen_labels=["transfer", "share"],
            ),
        ],
    ),
)

CANONICAL_PACKS: tuple[ConceptPack, ...] = (
    PH_SCALE,
    COVALENT_BONDING,
    IONIC_VS_COVALENT,
)
