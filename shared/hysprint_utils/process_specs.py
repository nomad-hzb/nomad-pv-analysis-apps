"""Single source of truth for per-process-type Excel columns and their NOMAD
archive field mappings.

Before this module existed, the same information was hand-duplicated in two
different shapes across two apps: apps/Excel_creator/sheet_experiment.py
(generate_steps_for_process - which Excel columns a process generates, in
what order, with what test values) and
apps/smart_databaser/config/field_mappings.json (which archive path each of
those columns autofills from). Adding or changing a process type meant
editing both by hand, plus (separately) up to six hand-maintained lists in
apps/smart_databaser/data_manager.py (AVAILABLE_PROCESSES,
CONFIGURABLE_PROCESS_TYPES, DEFAULT_CONFIG_BY_PROCESS_TYPE,
MATERIAL_GATED_PROCESS_TYPES, NUMERIC_CONFIG_FIELDS, BOOLEAN_CONFIG_FIELDS)
and a further set of separate, easy-to-miss copies in
apps/Excel_creator/voila_experiment_app.py's own inline config-control code
(configurable_processes, the solvents/solutes applicable-type lists, and the
per-process checkbox blocks) - a real gap of exactly this kind (Screen
Printing's config controls silently not rendering because
voila_experiment_app.py's own list was never updated) is what prompted this
module. See nomad-hzb/nomad-pv-analysis-apps#38.

Both apps now read from PROCESSES below instead of hand-duplicating any of
this. sheet_experiment.py still owns the per-process ASSEMBLY logic (which
fields appear in what order, and the handful of genuinely special-cased
branches - Spin Coating's single-vs-multi spin step naming, Experiment
Info's Ink Recycling variant) since that's real conditional logic, not
duplicated data; it looks up each field's label/test-value/dropdown from
here instead of hardcoding them inline. data_manager.py derives all of its
former hand-maintained lists from PROCESS_META, and loads archive field
paths directly from PROCESS_FIELDS/PROCESS_INDEXED_FIELDS instead of parsing
a separate JSON file.

Shape of one field entry (a dict): {"test": <test value>, "path": [...]} for
a single archive path, or {"test": <test value>, "paths": [[...], [...]]}
for alternative paths tried in order (first non-None wins) - same semantics
field_mappings.json used to have. Optional keys: "unit_verified" (default
True; False means the value is copied from the archive with NO unit
conversion applied and has NOT been confirmed to match the Excel column's
stated unit - check against the NOMAD web GUI before flipping to True),
"multiply" (a confirmed numeric unit-conversion factor applied before the
value is written/previewed - only add once verified against the actual
NOMAD quantity definition, never guessed), "dropdown" (inline Excel
data-validation choices). A field with no "path"/"paths" at all is a
deliberately-unmapped column (e.g. Datetime/Operator/Notes on every process
type, or Experiment Info's Date/Project_Name/Batch/Subbatch/Nomad
ID/Sample/Variation - see EXPERIMENT_INFO_NEVER_AUTOFILLED and
EXPERIMENT_INFO_COMPUTED_KEYS in data_manager.py for why those specifically
are never autofilled even though the mechanism exists).

Indexed (repeated) fields - e.g. "Solvent {n} name" - are grouped by the
config key that drives their repeat count (PROCESSES[type]["indexed"][key]),
since every field in that group loops together off the same counter. Each
entry's "path" carries a "{i}" placeholder resolved to the 0-based index.
"test" may be a plain value (repeated for every n) or a callable taking the
1-based n and returning the value, for tests that vary by index (e.g.
Solvent volumes). "mapping_range" (default (1, 5)) is how far
smart_databaser pre-generates archive-path lookups for autofill - this is
an autofill-coverage limit inherited unchanged from field_mappings.json's
original ranges, NOT the same as how many columns Excel_creator's own loop
will generate (that's uncapped, driven purely by the live config count, per
the GUI's own numeric-control max of 20) - a source archive with more than
`mapping_range` items simply won't autofill the extras, same pre-existing
behavior as before this module existed. Exactly one entry per config
concept should carry a `config_key` matching its group key (mirrors the old
field_mappings.json convention where only one indexed_fields entry per
concept carried the tag) - data_manager.infer_config_from_source_step uses
it.

Optional blocks (e.g. Spin Coating's Gas Quenching) are grouped by their
boolean config key (PROCESSES[type]["optional"][key]) - present only when
that config flag is True, same shape as a plain "fields" entry otherwise.

PROCESS_META holds what used to be split across data_manager.py's six lists
and voila_experiment_app.py's separate copies: "material_gated" (Material
name field gates progress counting), "numeric_config" (list of (config_key,
label, min, max) - GUI numeric controls, e.g. solvents/solutes counts),
"boolean_config" (list of (config_key, label) - GUI checkboxes, e.g. Gas
Quenching), "config_defaults" (starting config dict for a newly-added
process instance).
"""

# ---------------------------------------------------------------------------
# Shared coating-family blocks - Spin Coating / Dip Coating / Slot Die
# Coating / Inkjet Printing / Blade Coating / Screen Printing all share the
# same prefix (material/layer/solvent-solute/solution-properties) and suffix
# (annealing) around their own process-specific fields, mirroring
# sheet_experiment.py's existing `if process_name in [...]:` grouping.
# ---------------------------------------------------------------------------

_COATING_PREFIX_FIELDS = {
    "Datetime": {"test": "09.01.2026 10:19:00"},
    "Operator": {"test": "MaxMustermann"},
    "Material name": {
        "test": "Cs0.05(MA0.17FA0.83)0.95Pb(I0.83Br0.17)3",
        "path": ["layer", 0, "layer_material_name"],
    },
    "Layer type": {"test": "Absorber", "path": ["layer", 0, "layer_type"]},
    "Tool/GB name": {"test": "HZB-HySprintBox", "path": ["location"]},
    "Layer thickness [nm]": {"test": 100, "path": ["layer", 0, "layer_thickness"]},
}

_COATING_SOLUTION_PROPERTY_FIELDS = {
    "Viscosity [mPa*s]": {
        "test": 120,
        "path": ["solution", 0, "solution_viscosity"],
        "unit_verified": False,
    },
    "Contact angle [°]": {
        "test": 45,
        "path": ["solution", 0, "solution_contact_angle"],
        "unit_verified": False,
    },
    "Density [g/cm^3]": {
        "test": 1,
        "path": ["solution", 0, "solution_density"],
        "unit_verified": False,
    },
    "Surface tension [mN/m]": {
        "test": 72,
        "path": ["solution", 0, "solution_surface_tension"],
        "unit_verified": False,
    },
}

_COATING_SUFFIX_FIELDS = {
    "Annealing time [min]": {"test": 30, "path": ["annealing", "time"], "unit_verified": False},
    "Annealing temperature [°C]": {
        "test": 120,
        "path": ["annealing", "temperature"],
        "unit_verified": False,
    },
    "Annealing atmosphere": {"test": "Nitrogen", "path": ["annealing", "atmosphere"]},
    "Notes": {"test": "Process notes"},
}

_COATING_SOLVENT_INDEXED = {
    "config_key": "solvents",
    "fields": [
        {
            "excel_key": "Solvent {n} name",
            "test": lambda n: "DMF",
            "path": ["solution", 0, "solution_details", "solvent", "{i}", "chemical_2", "name"],
            "config_key": "solvents",
        },
        {
            "excel_key": "Solvent {n} volume [uL]",
            "test": lambda n: 10 * n,
            "path": ["solution", 0, "solution_details", "solvent", "{i}", "chemical_volume"],
        },
        {
            "excel_key": "Solvent {n} relative amount",
            "test": lambda n: 1.5,
            "path": ["solution", 0, "solution_details", "solvent", "{i}", "amount_relative"],
        },
        {
            "excel_key": "Solvent {n} chemical ID",
            "test": lambda n: "1592-461-04-2",
            "path": ["solution", 0, "solution_details", "solvent", "{i}", "chemical_id"],
        },
    ],
}

_COATING_SOLUTE_INDEXED = {
    "config_key": "solutes",
    "fields": [
        {
            "excel_key": "Solute {n} name",
            "test": lambda n: "PbI2",
            "path": ["solution", 0, "solution_details", "solute", "{i}", "name"],
            "config_key": "solutes",
        },
        {
            "excel_key": "Solute {n} Concentration [mM]",
            "test": lambda n: 1.42,
            "path": ["solution", 0, "solution_details", "solute", "{i}", "concentration_mol"],
            "unit_verified": False,
        },
        {
            "excel_key": "Solute {n} chemical ID",
            "test": lambda n: "2393-752-02-3",
            "path": ["solution", 0, "solution_details", "solute", "{i}", "chemical_id"],
        },
    ],
}

_GAS_QUENCHING_FIELDS = {
    "Gas": {"test": "Nitrogen", "path": ["quenching", "gas"]},
    "Gas quenching start time [s]": {
        "test": 5,
        "path": ["quenching", "starting_delay"],
        "unit_verified": False,
    },
    "Gas quenching duration [s]": {
        "test": 15,
        "path": ["quenching", "duration"],
        "unit_verified": False,
    },
    "Gas quenching flow rate [ml/s]": {
        "test": 20,
        "path": ["quenching", "flow_rate"],
        "unit_verified": False,
    },
    "Gas quenching pressure [bar]": {
        "test": 1.2,
        "path": ["quenching", "pressure"],
        "unit_verified": False,
    },
    "Gas quenching velocity [m/s]": {
        "test": 2.5,
        "path": ["quenching", "velocity"],
        "unit_verified": False,
    },
    "Gas quenching height [mm]": {
        "test": 10,
        "path": ["quenching", "height"],
        "unit_verified": False,
    },
    "Nozzle shape": {"test": "Round", "path": ["quenching", "nozzle_shape"]},
    "Nozzle size [mm²]": {"test": 3, "path": ["quenching", "nozzle_size"], "unit_verified": False},
}

_VACUUM_QUENCHING_FIELDS = {
    "Vacuum quenching start time [s]": {
        "test": 8,
        "path": ["quenching", "start_time"],
        "unit_verified": False,
    },
    "Vacuum quenching duration [s]": {
        "test": 20,
        "path": ["quenching", "duration"],
        "unit_verified": False,
    },
    "Vacuum quenching pressure [bar]": {
        "test": 0.01,
        "path": ["quenching", "pressure"],
        "unit_verified": False,
    },
}

_AIR_KNIFE_QUENCHING_FIELDS = {
    "Air knife angle [°]": {"test": 45, "path": ["quenching", "air_knife_angle"]},
    "Air knife gap [cm]": {"test": 0.5, "path": ["quenching", "air_knife_distance_to_thin_film"]},
    "Bead volume [mm/s]": {"test": 2, "path": ["quenching", "bead_volume"]},
    "Drying speed [cm/min]": {"test": 30, "path": ["quenching", "drying_speed"]},
}

_ATMOSPHERIC_FIELDS = {
    "Room temperature [°C]": {"test": 21},
    "rel. humidity [%]": {"test": "30"},
    "GB start oxygen level [ppm]": {"test": 0.1},
    "GB end oxygen level [ppm]": {"test": 0.1},
    "GB start water level [ppm]": {"test": 0.1},
    "GB end water level [ppm]": {"test": 0.1},
    "GB start temperature [°C]": {"test": 0.1},
    "GB end temperature [°C]": {"test": 0.1},
}
"""Not itself a "process" - appended to every real process (not Experiment
Info) when its "add_atmospheric" config flag is on. Kept here as the same
kind of field data as everything else, even though it's applied generically
by the renderer rather than being listed per-process."""

ATMOSPHERIC_CONFIG_KEY = "add_atmospheric"

_COATING_QUENCHING_NUMERIC = []
_COATING_QUENCHING_BOOLEAN_GAS_VACUUM = [
    ("gasquenching", "Gas Quenching"),
    ("vacuumquenching", "Vacuum Quenching"),
]

# ---------------------------------------------------------------------------
# Per-process-type specs
# ---------------------------------------------------------------------------

PROCESSES = {
    "Experiment Info": {
        "meta": {"material_gated": False, "numeric_config": [], "boolean_config": []},
        "fields": {
            "Date": {"test": "26-02-2025"},
            "Project_Name": {"test": "FiNa"},
            "Batch": {"test": "1"},
            "Subbatch": {"test": "1"},
            "Sample": {"test": "1"},
            "Nomad ID": {"test": ""},
            "Variation": {"test": "1000 rpm"},
            "Sample dimension": {
                "test": "1 cm x 1 cm",
                "path": ["substrate", "substrate_dimension"],
            },
            "Sample area [cm^2]": {"test": 0.16, "path": ["substrate", "solar_cell_area"]},
            "Number of pixels": {"test": 6, "path": ["substrate", "number_of_pixels"]},
            "Pixel area [cm^2]": {"test": 0.16, "path": ["substrate", "pixel_area"]},
            "Substrate material": {"test": "Soda Lime Glass", "path": ["substrate", "substrate"]},
            "Substrate conductive layer": {
                "test": "ITO",
                "path": ["substrate", "conducting_material", 0],
            },
            "Sheet Resistance [Ohms/square]": {
                "test": 15,
                "paths": [
                    ["substrate", "layer_sheet_resistance"],
                    ["substrate", "substrate_properties", 0, "layer_sheet_resistance"],
                ],
                "unit_verified": False,
            },
            "Transmission [%]": {
                "test": 90,
                "paths": [
                    ["substrate", "layer_transmission"],
                    ["substrate", "substrate_properties", 0, "layer_transmission"],
                ],
                "unit_verified": False,
            },
            "Number of junctions": {"test": 1, "path": ["sample", "number_of_junctions"]},
            "Notes": {"test": "Test excel"},
        },
        "fields_ink_recycling": {
            "Date": {"test": "27-05-2025"},
            "Project_Name": {"test": "FiNa"},
            "Batch": {"test": "1"},
            "Subbatch": {"test": "1"},
            "Sample": {"test": "1"},
            "Nomad ID": {"test": ""},
            "Variation": {"test": "Some variation"},
        },
    },
    "Cleaning O2-Plasma": {
        "meta": {
            "material_gated": False,
            "numeric_config": [("solvents", "Solvents", 0, 20)],
            "boolean_config": [],
            "config_defaults": {"solvents": 2},
        },
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Gas-Plasma Gas": {"test": "Oxygen", "path": ["cleaning_plasma", 0, "plasma_type"]},
            "Gas-Plasma Time [s]": {
                "test": 180,
                "path": ["cleaning_plasma", 0, "time"],
                "multiply": 60,
            },
            "Gas-Plasma Power [W]": {
                "test": 50,
                "path": ["cleaning_plasma", 0, "power"],
                "unit_verified": False,
            },
            "Notes": {"test": "Test cleaning"},
        },
        "indexed": {
            "solvents": [
                {
                    "excel_key": "Solvent {n}",
                    "test": lambda n: "Hellmanex",
                    "path": ["cleaning", "{i}", "name"],
                    "config_key": "solvents",
                },
                {
                    "excel_key": "Time {n} [s]",
                    "test": lambda n: 30 + n,
                    "path": ["cleaning", "{i}", "time"],
                    "multiply": 60,
                },
                {
                    "excel_key": "Temperature {n} [°C]",
                    "test": lambda n: 60 + n,
                    "path": ["cleaning", "{i}", "temperature"],
                    "unit_verified": False,
                },
            ]
        },
    },
    "Cleaning UV-Ozone": {
        "meta": {
            "material_gated": False,
            "numeric_config": [("solvents", "Solvents", 0, 20)],
            "boolean_config": [],
            "config_defaults": {"solvents": 2},
        },
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "UV-Ozone Time [s]": {"test": 900, "path": ["cleaning_uv", 0, "time"], "multiply": 60},
            "Notes": {"test": "Test cleaning"},
        },
        "indexed": {
            "solvents": [
                {
                    "excel_key": "Solvent {n}",
                    "test": lambda n: "Hellmanex",
                    "path": ["cleaning", "{i}", "name"],
                    "config_key": "solvents",
                },
                {
                    "excel_key": "Time {n} [s]",
                    "test": lambda n: 30 + n,
                    "path": ["cleaning", "{i}", "time"],
                    "multiply": 60,
                },
                {
                    "excel_key": "Temperature {n} [°C]",
                    "test": lambda n: 60 + n,
                    "path": ["cleaning", "{i}", "temperature"],
                    "unit_verified": False,
                },
            ]
        },
    },
    "Spin Coating": {
        "meta": {
            "material_gated": True,
            "numeric_config": [
                ("solvents", "Solvents", 0, 20),
                ("solutes", "Solutes", 0, 20),
                ("spinsteps", "Steps", 1, 5),
            ],
            "boolean_config": [
                ("antisolvent", "Antisolvent"),
                ("gasquenching", "Gas Quenching"),
                ("vacuumquenching", "Vacuum Quenching"),
            ],
            "config_defaults": {
                "solvents": 1,
                "solutes": 1,
                "spinsteps": 1,
                "antisolvent": False,
                "gasquenching": False,
                "vacuumquenching": False,
            },
        },
        "fields": {
            **_COATING_PREFIX_FIELDS,
            **_COATING_SOLUTION_PROPERTY_FIELDS,
            "Solution volume [uL]": {
                "test": 100,
                "path": ["solution", 0, "solution_volume"],
                "unit_verified": False,
            },
            "Spin Delay [s]": {"test": 0.5},
            "Rotation speed [rpm]": {
                "test": 1500,
                "path": ["recipe_steps", 0, "speed"],
                "unit_verified": False,
            },
            "Rotation time [s]": {
                "test": 30,
                "path": ["recipe_steps", 0, "time"],
                "unit_verified": False,
            },
            "Acceleration [rpm/s]": {
                "test": 500,
                "path": ["recipe_steps", 0, "acceleration"],
                "unit_verified": False,
            },
            **_COATING_SUFFIX_FIELDS,
        },
        "indexed": {
            "solvents": _COATING_SOLVENT_INDEXED["fields"],
            "solutes": _COATING_SOLUTE_INDEXED["fields"],
            "spinsteps": [
                {
                    "excel_key": "Rotation speed {n} [rpm]",
                    "test": lambda n: 3000 + n,
                    "path": ["recipe_steps", "{i}", "speed"],
                    "unit_verified": False,
                    "config_key": "spinsteps",
                },
                {
                    "excel_key": "Rotation time {n} [s]",
                    "test": lambda n: 30 + n,
                    "path": ["recipe_steps", "{i}", "time"],
                    "unit_verified": False,
                },
                {
                    "excel_key": "Acceleration {n} [rpm/s]",
                    "test": lambda n: 1000 + n,
                    "path": ["recipe_steps", "{i}", "acceleration"],
                    "unit_verified": False,
                },
            ],
        },
        "optional": {
            "antisolvent": {
                "Anti solvent name": {
                    "test": "Toluene",
                    "path": ["quenching", "anti_solvent_2", "name"],
                },
                "Anti solvent volume [ml]": {
                    "test": 0.3,
                    "path": ["quenching", "anti_solvent_volume"],
                    "unit_verified": False,
                },
                "Anti solvent dropping time [s]": {
                    "test": 25,
                    "path": ["quenching", "anti_solvent_dropping_time"],
                    "unit_verified": False,
                },
                "Anti solvent dropping speed [ul/s]": {
                    "test": 50,
                    "path": ["quenching", "anti_solvent_dropping_flow_rate"],
                    "unit_verified": False,
                },
                "Anti solvent dropping heigt [mm]": {
                    "test": 30,
                    "path": ["quenching", "anti_solvent_dropping_height"],
                    "unit_verified": False,
                },
            },
            "gasquenching": _GAS_QUENCHING_FIELDS,
            "vacuumquenching": _VACUUM_QUENCHING_FIELDS,
        },
    },
    "Slot Die Coating": {
        # KNOWN PRE-EXISTING BUG, preserved as-is (not silently fixed by this
        # migration): "gasquenching"/"vacuumquenching" are declared applicable below so
        # their checkboxes render in smart_databaser's GUI (same as before this
        # migration), but there is deliberately no "optional" block for either key here,
        # matching the original sheet_experiment.py Slot Die Coating branch, which never
        # read either config flag - toggling these checkboxes has always had zero effect
        # on the generated Excel columns. Flagging for a future decision (remove the
        # dead checkboxes, or wire them up to real gas/vacuum quenching blocks like Spin
        # Coating's), not fixing either way here - out of scope for this migration.
        # Same reasoning covers field_mappings.json's old (also phantom, also dropped
        # here) Gas/Vacuum quenching archive paths for Slot Die Coating - they could
        # never have matched a real field_spec either, since the columns they'd map
        # from are never generated.
        "meta": {
            "material_gated": True,
            "numeric_config": [("solvents", "Solvents", 0, 20), ("solutes", "Solutes", 0, 20)],
            "boolean_config": [
                ("gasquenching", "Gas Quenching"),
                ("vacuumquenching", "Vacuum Quenching"),
            ],
            "config_defaults": {
                "solvents": 1,
                "solutes": 1,
                "gasquenching": False,
                "vacuumquenching": False,
            },
        },
        "fields": {
            **_COATING_PREFIX_FIELDS,
            **_COATING_SOLUTION_PROPERTY_FIELDS,
            "Solution volume [uL]": {
                "test": 100,
                "path": ["solution", 0, "solution_volume"],
                "unit_verified": False,
            },
            "Flow rate [ul/min]": {
                "test": 25,
                "path": ["properties", "flow_rate"],
                "unit_verified": False,
            },
            "Head gap [mm]": {
                "test": 0.3,
                "path": ["properties", "slot_die_head_distance_to_thinfilm"],
                "unit_verified": False,
            },
            "Speed [mm/s]": {
                "test": 15,
                "path": ["properties", "slot_die_head_speed"],
                "unit_verified": False,
            },
            **_AIR_KNIFE_QUENCHING_FIELDS,
            "Chuck heating temperature [°C]": {
                "test": 25,
                "path": ["properties", "temperature"],
                "unit_verified": False,
            },
            **_COATING_SUFFIX_FIELDS,
        },
        "indexed": {
            "solvents": _COATING_SOLVENT_INDEXED["fields"],
            "solutes": _COATING_SOLUTE_INDEXED["fields"],
        },
    },
    "Dip Coating": {
        # field_mappings.json used to carry a "Solution volume [uL]" path for Dip
        # Coating too, but sheet_experiment.py's Dip Coating branch never actually
        # generates that column (only Spin/Slot Die/Blade/Screen Printing do) - a
        # phantom mapping entry that could never match a real field_spec, confirmed
        # dead by this migration's before/after diff. Not carried over (same for
        # Inkjet Printing's identical phantom entry below).
        "meta": {
            "material_gated": True,
            "numeric_config": [],
            "boolean_config": [],
        },
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Material name": {
                "test": "Cs0.05(MA0.17FA0.83)0.95Pb(I0.83Br0.17)3",
                "path": ["layer", 0, "layer_material_name"],
            },
            "Layer type": {"test": "Absorber", "path": ["layer", 0, "layer_type"]},
            "Tool/GB name": {"test": "HZB-HySprintBox", "path": ["location"]},
            # "Layer thickness [nm]" IS generated (same shared prefix as every other
            # coating process) but deliberately has no "path" - field_mappings.json's old
            # Dip Coating entry never mapped it either (that gap was originally tracked in
            # config/schema_coverage.md, retired by this migration since PROCESSES itself
            # now shows unmapped fields directly - "already fixed for Spin Coating/Slot
            # Die Coating/Blade Coating/Inkjet Printing...Dip Coating's identical gap was
            # deliberately left unfixed pending a real batch to verify against").
            "Layer thickness [nm]": {"test": 100},
            **_COATING_SOLUTION_PROPERTY_FIELDS,
            "Dipping duration [s]": {
                "test": 15,
                "path": ["properties", "time"],
                "unit_verified": False,
            },
            **_COATING_SUFFIX_FIELDS,
        },
        "indexed": {
            "solvents": [
                {
                    "excel_key": "Solvent {n} name",
                    "test": lambda n: "DMF",
                    "path": ["solution", 0, "solution_details", "solvent", "{i}", "name"],
                    "config_key": "solvents",
                }
            ],
            "solutes": [
                {
                    "excel_key": "Solute {n} name",
                    "test": lambda n: "PbI2",
                    "path": ["solution", 0, "solution_details", "solute", "{i}", "name"],
                    "config_key": "solutes",
                },
                {
                    "excel_key": "Solute {n} Concentration [mM]",
                    "test": lambda n: 1.42,
                    "path": [
                        "solution",
                        0,
                        "solution_details",
                        "solute",
                        "{i}",
                        "concentration_mol",
                    ],
                    "unit_verified": False,
                },
            ],
        },
        # NOTE: Dip Coating's Excel columns don't actually include "Layer thickness [nm]"
        # or per-solvent volume/relative-amount/chemical-ID (sheet_experiment.py never
        # generated them for this process type) - see field_mappings.json's historical
        # readme: "Dip Coating still has the identical gap, still deliberately unfixed
        # pending a real batch to verify against." Preserved as-is, not fixed here.
    },
    "Blade Coating": {
        "meta": {
            "material_gated": True,
            "numeric_config": [("solvents", "Solvents", 0, 20), ("solutes", "Solutes", 0, 20)],
            "boolean_config": [
                ("gasquenching", "Gas Quenching"),
                ("vacuumquenching", "Vacuum Quenching"),
            ],
            "config_defaults": {
                "solvents": 1,
                "solutes": 1,
                "gasquenching": False,
                "vacuumquenching": False,
            },
        },
        "fields": {
            **_COATING_PREFIX_FIELDS,
            **_COATING_SOLUTION_PROPERTY_FIELDS,
            "Solution volume [uL]": {
                "test": 100,
                "path": ["solution", 0, "solution_volume"],
                "unit_verified": False,
            },
            "Blade Speed [mm/s]": {
                "test": 15,
                "path": ["properties", "blade_speed"],
                "unit_verified": False,
            },
            "Dispensed Ink Volume [uL]": {
                "test": 100,
                "path": ["properties", "dispensed_volume"],
                "unit_verified": False,
            },
            "Blade Gap [um]": {
                "test": 300,
                "path": ["properties", "blade_substrate_gap"],
                "unit_verified": False,
            },
            "Blade Size": {"test": 25, "path": ["properties", "blade_size"]},
            "Coating Width [mm]": {
                "test": 20,
                "path": ["properties", "coating_width"],
                "unit_verified": False,
            },
            "Coating Length [mm]": {
                "test": 70,
                "path": ["properties", "coating_length"],
                "unit_verified": False,
            },
            "Dead Length [mm]": {
                "test": 40,
                "path": ["properties", "dead_length"],
                "unit_verified": False,
            },
            "Bed Temperature [°C]": {
                "test": 25,
                "path": ["properties", "bed_temperature"],
                "unit_verified": False,
            },
            "Ink Temperature [°C]": {
                "test": 25,
                "path": ["properties", "ink_temperature"],
                "unit_verified": False,
            },
            **_COATING_SUFFIX_FIELDS,
        },
        "indexed": {
            "solvents": _COATING_SOLVENT_INDEXED["fields"],
            "solutes": _COATING_SOLUTE_INDEXED["fields"],
        },
        "optional": {
            # KNOWN GAP, preserved as-is (not silently fixed here): "Nozzle shape"/
            # "Nozzle size [mm²]" ARE generated Excel columns for Blade Coating's Gas
            # Quenching block (identical to Spin Coating's), but field_mappings.json
            # never had archive paths for them here specifically, even though the same
            # paths ARE mapped for Spin Coating/Slot Die Coating's own Gas Quenching
            # (quenching.nozzle_shape/quenching.nozzle_size) - originally tracked in
            # config/schema_coverage.md's "Real, worth-investigating gaps" (retired by
            # this migration): "Likely the same paths apply; not yet verified against a
            # real Blade Coating batch with Gas Quenching data."
            # Deliberately NOT inferring/adding those paths here just because they'd be
            # mechanically easy to copy from _GAS_QUENCHING_FIELDS - same discipline as
            # unit_verified: only add a path once actually confirmed, not guessed.
            "gasquenching": {
                **{
                    k: v
                    for k, v in _GAS_QUENCHING_FIELDS.items()
                    if k not in ("Nozzle shape", "Nozzle size [mm²]")
                },
                "Nozzle shape": {"test": "Round"},
                "Nozzle size [mm²]": {"test": 3},
            }
        },
    },
    # "Screen Printing" deliberately NOT included yet: it's mid-review on a separate
    # branch/PR (nomad-hzb/nomad-pv-analysis-apps#37, off main, not merged) and this
    # module is built against main's current process types on purpose, so this branch
    # stays fully decoupled from that PR per explicit user decision - merging this
    # unification must not introduce Screen Printing as a side effect before #37 lands.
    # Add it back here as this branch's last step, once #37 has merged and this branch
    # is rebased onto main - the full spec (fields/indexed/optional/meta, already
    # written and validated once) is saved for reuse, not lost.
    "Inkjet Printing": {
        "meta": {
            "material_gated": True,
            "numeric_config": [("solvents", "Solvents", 0, 20), ("solutes", "Solutes", 0, 20)],
            "boolean_config": [("gavd", "GAVD")],
            "config_defaults": {"solvents": 1, "solutes": 1, "annealing": False, "gavd": False},
        },
        "fields": {
            **_COATING_PREFIX_FIELDS,
            **_COATING_SOLUTION_PROPERTY_FIELDS,
            "Printhead name": {
                "test": "Spectra 0.8uL",
                "path": ["properties", "print_head_properties", "print_head_name"],
            },
            "Number of active nozzles": {
                "test": 128,
                "path": ["properties", "print_head_properties", "number_of_active_print_nozzles"],
            },
            "Active nozzles": {
                "test": "all",
                "path": ["properties", "print_head_properties", "active_nozzles"],
            },
            "Droplet density X [dpi]": {
                "test": 400,
                "path": ["properties", "drop_density"],
                "unit_verified": False,
            },
            "Droplet density Y [dpi]": {
                "test": 300,
                "path": ["properties", "drop_density_y"],
                "unit_verified": False,
            },
            "Quality factor": {"test": 3, "path": ["print_head_path", "quality_factor"]},
            "Step size": {"test": 10, "path": ["print_head_path", "step_size"]},
            "Printing direction": {"test": 10, "path": ["print_head_path", "directional"]},
            "Number of swaths": {"test": 10, "path": ["print_head_path", "swaths"]},
            "Printed area [mm²]": {
                "test": 100,
                "path": ["properties", "printed_area"],
                "unit_verified": False,
            },
            "Droplet per second [1/s]": {
                "test": 5000,
                "path": ["properties", "print_head_properties", "print_nozzle_drop_frequency"],
                "unit_verified": False,
            },
            "Droplet volume [pl]": {
                "test": 10,
                "path": ["properties", "print_head_properties", "print_nozzle_drop_volume"],
                "unit_verified": False,
            },
            "Ink reservoir pressure [bar]": {
                "test": 0.3,
                "path": ["properties", "cartridge_pressure"],
                "unit_verified": False,
            },
            "Table temperature [°C]": {
                "test": 40,
                "path": ["properties", "substrate_temperature"],
                "unit_verified": False,
            },
            "Dropping Height [mm]": {
                "test": 12,
                "path": ["properties", "print_head_properties", "print_head_distance_to_substrate"],
                "unit_verified": False,
            },
            "Substrate thickness [mm]": {
                "test": 20,
                "path": ["properties", "substrate_height"],
                "unit_verified": False,
            },
            "Printing speed [mm/s]": {
                "test": 10,
                "path": ["properties", "print_head_properties", "print_speed"],
                "unit_verified": False,
            },
            "Print head angle [deg]": {
                "test": 13,
                "path": ["properties", "print_head_properties", "print_head_angle"],
                "unit_verified": False,
            },
            "Nozzle temperature [°C]": {
                "test": 35,
                "path": ["properties", "print_head_properties", "print_head_temperature"],
                "unit_verified": False,
            },
            "Nozzle voltage config file": {
                "test": "testfile.txt",
                "path": ["nozzle_voltage_profile", "config_file"],
            },
            "Image used": {"test": "Square inch 300 dpi", "path": ["properties", "image_used"]},
            **_COATING_SUFFIX_FIELDS,
        },
        "indexed": {
            "solvents": _COATING_SOLVENT_INDEXED["fields"],
            "solutes": _COATING_SOLUTE_INDEXED["fields"],
        },
        "optional": {
            "gavd": {
                "GAVD Gas": {
                    "test": "Nitrogen",
                    "path": ["quenching", "gas_quenching_properties", "gas"],
                },
                "GAVD start time [s]": {
                    "test": 5,
                    "path": ["quenching", "vacuum_properties", "start_time"],
                    "unit_verified": False,
                },
                "GAVD vacuum pressure [mbar]": {
                    "test": 10,
                    "path": ["quenching", "vacuum_properties", "pressure"],
                    "unit_verified": False,
                },
                "GAVD temperature [°C]": {
                    "test": 25,
                    "path": ["quenching", "vacuum_properties", "temperature"],
                    "unit_verified": False,
                },
                "GAVD vacuum time [s]": {
                    "test": 15,
                    "path": ["quenching", "vacuum_properties", "duration"],
                    "unit_verified": False,
                },
                "Gas flow duration [s]": {
                    "test": 15,
                    "path": ["quenching", "gas_quenching_properties", "duration"],
                    "unit_verified": False,
                },
                "Gas flow pressure [mbar]": {
                    "test": 100,
                    "path": ["quenching", "gas_quenching_properties", "pressure"],
                    "unit_verified": False,
                },
                "Nozzle shape": {
                    "test": "round",
                    "path": ["quenching", "gas_quenching_properties", "nozzle_shape"],
                },
                "Nozzle type": {
                    "test": "mesh",
                    "path": ["quenching", "gas_quenching_properties", "nozzle_type"],
                },
                "GAVD comment": {"test": "GAVD Note", "path": ["quenching", "comment"]},
            }
        },
    },
    "Evaporation": {
        # "Sublimation" is NOT a selectable process type (never in AVAILABLE_PROCESSES
        # or voila_experiment_app.py's own processes list) - it exists only as a legacy
        # renderer-level alias: sheet_experiment.py's original code accepted
        # `process_name == "Evaporation" or process_name == "Sublimation"` and generated
        # identical columns for either, with zero archive paths for "Sublimation" either
        # way (the real parser's parse() only substring-matches 'evaporation' in the
        # column header). The renderer preserves that alias without giving Sublimation
        # its own PROCESSES entry, so it stays unreachable via any process picker, same
        # as before this migration.
        "meta": {"material_gated": True, "numeric_config": [], "boolean_config": []},
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Material name": {"test": "PCBM", "path": ["layer", 0, "layer_material_name"]},
            "Layer type": {
                "test": "Electron Transport Layer",
                "path": ["layer", 0, "layer_type"],
            },
            "Tool/GB name": {"test": "Hysprint Evap", "path": ["location"]},
            "Organic": {"test": True},
            "Sample holder width [mm]": {
                "test": "25",
                "paths": [
                    ["organic_evaporation", 0, "sample_holder"],
                    ["inorganic_evaporation", 0, "sample_holder"],
                ],
                "unit_verified": False,
            },
            "Base pressure [bar]": {
                "test": 1e-6,
                "paths": [
                    ["organic_evaporation", 0, "pressure"],
                    ["inorganic_evaporation", 0, "pressure"],
                ],
                "unit_verified": False,
            },
            "Pressure start [bar]": {
                "test": 5e-6,
                "paths": [
                    ["organic_evaporation", 0, "pressure_start"],
                    ["inorganic_evaporation", 0, "pressure_start"],
                ],
                "unit_verified": False,
            },
            "Pressure end [bar]": {
                "test": 3e-6,
                "paths": [
                    ["organic_evaporation", 0, "pressure_end"],
                    ["inorganic_evaporation", 0, "pressure_end"],
                ],
                "unit_verified": False,
            },
            "Source temperature start[°C]": {
                "test": 150,
                "paths": [
                    ["organic_evaporation", 0, "temparature", 0],
                    ["inorganic_evaporation", 0, "temparature", 0],
                ],
                "unit_verified": False,
            },
            "Source temperature end[°C]": {
                "test": 160,
                "paths": [
                    ["organic_evaporation", 0, "temparature", 1],
                    ["inorganic_evaporation", 0, "temparature", 1],
                ],
                "unit_verified": False,
            },
            "Substrate temperature [°C]": {
                "test": 25,
                "paths": [
                    ["organic_evaporation", 0, "substrate_temparature"],
                    ["inorganic_evaporation", 0, "substrate_temparature"],
                ],
                "unit_verified": False,
            },
            "Thickness [nm]": {
                "test": 100,
                "paths": [
                    ["organic_evaporation", 0, "thickness"],
                    ["inorganic_evaporation", 0, "thickness"],
                ],
                "unit_verified": False,
            },
            "Rate start [angstrom/s]": {
                "test": 0.5,
                "paths": [
                    ["organic_evaporation", 0, "start_rate"],
                    ["inorganic_evaporation", 0, "start_rate"],
                ],
                "unit_verified": False,
            },
            "Rate target [angstrom/s]": {
                "test": 1.0,
                "paths": [
                    ["organic_evaporation", 0, "target_rate"],
                    ["inorganic_evaporation", 0, "target_rate"],
                ],
                "unit_verified": False,
            },
            "Tooling factor": {
                "test": 1.5,
                "paths": [
                    ["organic_evaporation", 0, "tooling_factor"],
                    ["inorganic_evaporation", 0, "tooling_factor"],
                ],
            },
            "Notes": {"test": "Test note"},
        },
        # NOTE: "Organic" is intentionally NOT mapped to any archive path here - it
        # reflects an Excel SECTION choice, not a real archive attribute; the real
        # Organic/Inorganic split is read back via data_manager._DERIVED_FIELDS
        # (_derive_evaporation_organic), unchanged by this migration.
    },
    "Co-Evaporation": {
        "meta": {
            "material_gated": True,
            "numeric_config": [("materials", "Materials", 1, 10)],
            "boolean_config": [],
            "config_defaults": {"materials": 2},
        },
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Material name": {"test": "Aluminium", "path": ["layer", 0, "layer_material_name"]},
            "Layer type": {"test": "Electrode", "path": ["layer", 0, "layer_type"]},
            "Tool/GB name": {"test": "IRIS Evap", "path": ["location"]},
            "Notes": {"test": "Test note co-evaporation"},
        },
        "indexed": {
            "materials": [
                {
                    "excel_key": "Material name {n}",
                    "test": lambda n: "Cupper",
                    "path": ["perovskite_evaporation", "{i}", "chemical_2", "name"],
                    "config_key": "materials",
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Source temperature start {n}[°C]",
                    "test": lambda n: 100 + 10 + n,
                    "path": ["perovskite_evaporation", "{i}", "temparature", 0],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Source temperature end {n}[°C]",
                    "test": lambda n: 110 + 10 + n,
                    "path": ["perovskite_evaporation", "{i}", "temparature", 1],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Thickness {n} [nm]",
                    "test": lambda n: 20 + n,
                    "path": ["perovskite_evaporation", "{i}", "thickness"],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Rate {n} [angstrom/s]",
                    "test": lambda n: 0.5 + n,
                    "path": ["perovskite_evaporation", "{i}", "target_rate"],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Base pressure {n} [bar]",
                    "test": lambda n: 1e-6,
                    "path": ["perovskite_evaporation", "{i}", "pressure"],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Pressure start {n} [bar]",
                    "test": lambda n: 5e-6,
                    "path": ["perovskite_evaporation", "{i}", "pressure_start"],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Pressure end {n} [bar]",
                    "test": lambda n: 3e-6,
                    "path": ["perovskite_evaporation", "{i}", "pressure_end"],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Substrate temperature {n} [°C]",
                    "test": lambda n: 25,
                    "path": ["perovskite_evaporation", "{i}", "substrate_temparature"],
                    "unit_verified": False,
                    "mapping_range": (1, 10),
                },
                {
                    "excel_key": "Tooling factor {n}",
                    "test": lambda n: 1.0 + 0.1 + n,
                    "path": ["perovskite_evaporation", "{i}", "tooling_factor"],
                    "mapping_range": (1, 10),
                },
            ]
        },
    },
    "Sputtering": {
        "meta": {"material_gated": True, "numeric_config": [], "boolean_config": []},
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Material name": {"test": "TiO2", "path": ["layer", 0, "layer_material_name"]},
            "Layer type": {
                "test": "Electron Transport Layer",
                "path": ["layer", 0, "layer_type"],
            },
            "Tool/GB name": {"test": "Hysprint tool", "path": ["location"]},
            "Gas": {"test": "Argon", "path": ["processes", 0, "gas_2", "name"]},
            "Temperature [°C]": {
                "test": 200,
                "path": ["processes", 0, "temperature"],
                "unit_verified": False,
            },
            "Pressure [mbar]": {
                "test": 0.01,
                "path": ["processes", 0, "pressure"],
                "unit_verified": False,
            },
            "Deposition time [s]": {
                "test": 300,
                "path": ["processes", 0, "deposition_time"],
                "unit_verified": False,
            },
            "Burn in time [s]": {
                "test": 60,
                "path": ["processes", 0, "burn_in_time"],
                "unit_verified": False,
            },
            "Power [W]": {"test": 150, "path": ["processes", 0, "power"], "unit_verified": False},
            "Rotation rate [rpm]": {
                "test": 30,
                "path": ["processes", 0, "rotation_rate"],
                "unit_verified": False,
            },
            "Thickness [nm]": {
                "test": 50,
                "path": ["processes", 0, "thickness"],
                "unit_verified": False,
            },
            "Gas flow rate [cm^3/min]": {
                "test": 20,
                "path": ["processes", 0, "gas_flow_rate"],
                "unit_verified": False,
            },
            "Notes": {"test": "Notes Sputtering"},
        },
    },
    "Laser Scribing": {
        "meta": {"material_gated": False, "numeric_config": [], "boolean_config": []},
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Laser wavelength [nm]": {"test": 532, "path": ["properties", "laser_wavelength"]},
            "Laser pulse time [ps]": {"test": 8, "path": ["properties", "laser_pulse_time"]},
            "Laser pulse frequency [kHz]": {
                "test": 80,
                "path": ["properties", "laser_pulse_frequency"],
            },
            "Speed [mm/s]": {"test": 100, "path": ["properties", "speed"]},
            "Fluence [J/cm2]": {"test": 0.5, "path": ["properties", "fluence"]},
            "Power [%]": {"test": 75, "path": ["properties", "power_in_percent"]},
            "Recipe file": {"test": "test_scribing_recipe.xml", "path": ["recipe_file"]},
            "Dead area [cm2]": {"test": 2, "path": ["properties", "dead_area"]},
            "Width of cell [mm]": {"test": 5, "path": ["properties", "cell_width"]},
            "Number of cells": {"test": 6, "path": ["properties", "number_of_cells"]},
            "Notes": {"test": "Laser Note"},
        },
    },
    "ALD": {
        "meta": {"material_gated": True, "numeric_config": [], "boolean_config": []},
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Material name": {"test": "Al2O3", "path": ["layer", 0, "layer_material_name"]},
            "Layer type": {
                "test": "Electron Transport Layer",
                "path": ["layer", 0, "layer_type"],
            },
            "Tool/GB name": {"test": "IRIS ALD", "path": ["location"]},
            "Source": {"test": "TMA", "path": ["properties", "source"]},
            "Thickness [nm]": {
                "test": 25,
                "path": ["properties", "thickness"],
                "unit_verified": False,
            },
            "Temperature [°C]": {
                "test": 150,
                "path": ["properties", "temperature"],
                "unit_verified": False,
            },
            "Rate [A/s]": {"test": 0.1, "path": ["properties", "rate"], "unit_verified": False},
            "Time [s]": {"test": 1800, "path": ["properties", "time"], "unit_verified": False},
            "Number of cycles": {"test": 250, "path": ["properties", "number_of_cycles"]},
            "Precursor 1": {"test": "TMA", "path": ["properties", "material", "material", "name"]},
            "Pulse duration 1 [s]": {
                "test": 0.2,
                "path": ["properties", "material", "pulse_duration"],
                "unit_verified": False,
            },
            "Manifold temperature 1 [°C]": {
                "test": 80,
                "path": ["properties", "material", "manifold_temperature"],
                "unit_verified": False,
            },
            "Bottle temperature 1 [°C]": {
                "test": 25,
                "path": ["properties", "material", "bottle_temperature"],
                "unit_verified": False,
            },
            "Precursor 2 (Oxidizer/Reducer)": {
                "test": "H2O",
                "path": ["properties", "oxidizer_reducer", "material", "name"],
            },
            "Pulse duration 2 [s]": {
                "test": 0.1,
                "path": ["properties", "oxidizer_reducer", "pulse_duration"],
                "unit_verified": False,
            },
            "Manifold temperature 2 [°C]": {
                "test": 70,
                "path": ["properties", "oxidizer_reducer", "manifold_temperature"],
                "unit_verified": False,
            },
            "Notes": {"test": "ALD Note"},
        },
    },
    "Annealing": {
        "meta": {"material_gated": False, "numeric_config": [], "boolean_config": []},
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Annealing time [min]": {
                "test": 60,
                "path": ["annealing", "time"],
                "unit_verified": False,
            },
            "Annealing temperature [°C]": {
                "test": 150,
                "path": ["annealing", "temperature"],
                "unit_verified": False,
            },
            "Annealing athmosphere": {"test": "Nitrogen", "path": ["annealing", "atmosphere"]},
            "Relative humidity [%]": {"test": 35, "path": ["atmosphere", "relative_humidity"]},
            "Notes": {"test": "Test annealing process"},
        },
    },
    "Generic Process": {
        "meta": {"material_gated": False, "numeric_config": [], "boolean_config": []},
        "fields": {
            "Datetime": {"test": "09.01.2026 10:19:00"},
            "Operator": {"test": "MaxMustermann"},
            "Name": {"test": "Test Generic Process", "path": ["name"]},
            "Notes": {"test": "This is a test generic process"},
        },
        # NOTE: most Generic Process columns (Room temperature/rel. humidity/GB
        # oxygen-water-temperature) ARE autofillable in the real app, but not via a fixed
        # archive path - hysprint_batch_parser.py's map_generic_parameters() stores every
        # column except Notes/Name as a flat process_parameters list, read back via
        # data_manager._DERIVED_FIELDS. Not representable as a plain path here; unchanged
        # by this migration.
    },
    "Ink Recycling": {
        "meta": {
            "material_gated": False,
            "numeric_config": [
                ("solvents", "Solvents", 0, 20),
                ("solutes", "Solutes", 0, 20),
                ("precursors", "Precursors", 0, 10),
            ],
            "boolean_config": [],
            "config_defaults": {"solvents": 1, "solutes": 1, "precursors": 1},
        },
        "fields": {
            "Functional liquid name": {"test": "FL"},
            "Functional liquid volume [ml]": {"test": 25},
            "Dissolving temperature [°C]": {"test": 60},
            "Filter material": {"test": "Paper"},
            "Filter size [mm]": {"test": 0.45},
            "Filter weight [g]": {"test": 0.5},
            "Recovered solute [g]": {"test": 4.2},
            "Yield [%]": {"test": 84},
            "Notes": {"test": "Test recycling process"},
        },
        "indexed": {
            "solvents": [
                {"excel_key": "Datetime", "test": lambda n: "09.01.2026 10:19:00"},
                {"excel_key": "Operator", "test": lambda n: "MaxMustermann"},
                {
                    "excel_key": "Solvent {n} name",
                    "test": lambda n: f"DMF {n}",
                    "config_key": "solvents",
                },
                {"excel_key": "Solvent {n} volume [ml]", "test": lambda n: 10 * n},
            ],
            "solutes": [
                {
                    "excel_key": "Solute {n} name",
                    "test": lambda n: f"PbI2 {n}",
                    "config_key": "solutes",
                },
                {"excel_key": "Solute {n} concentration [M]", "test": lambda n: 1.5 * n},
                {"excel_key": "Solute {n} amount [g]", "test": lambda n: 5.0 * n},
                {"excel_key": "Solute {n} moles [mol]", "test": lambda n: 0.02 * n},
            ],
            "precursors": [
                {
                    "excel_key": "Precursor {n} name",
                    "test": lambda n: f"MAI {n}",
                    "config_key": "precursors",
                },
                {"excel_key": "Precursor {n} moles [mol]", "test": lambda n: 0.01 * n},
            ],
        },
        # NOTE: 0/59 covered on the autofill side - Ink Recycling is ingested by an
        # entirely separate mapper (nomad_hysprint.parsers.file_parser
        # .ink_recycling_mappers.map_ink_recycling), never fetched/mapped. No archive
        # paths exist here yet; unchanged by this migration. "Datetime"/"Operator" are
        # unusually repeated inside the solvents loop (once per solvent index) - this
        # mirrors sheet_experiment.py's own (likely accidental, but behavior-preserving)
        # original structure, not something introduced by this migration.
    },
}

# Generic Process is the one process type with NO Method column in the real archive
# schema at all (HySprint_Process has no method concept) - resolved by m_def suffix
# match instead of a field_mappings.json-style path; kept out of PROCESSES' path data
# since it's not a per-column mapping. See data_manager._M_DEF_PROCESS_TYPES.

# Two confirmed-dead declarations from the pre-migration hand-maintained lists were
# deliberately NOT carried over here (found via this migration's before/after
# behavioral diff, not guessed): (1) Evaporation's "carbon_paste" boolean config
# (was in data_manager.py's old DEFAULT_CONFIG_BY_PROCESS_TYPE/BOOLEAN_CONFIG_FIELDS)
# never actually rendered in either app - "Evaporation" was never added to
# CONFIGURABLE_PROCESS_TYPES, which gui_components.py's control-rendering gates on,
# and sheet_experiment.py's Evaporation branch never read a "carbon_paste" config key
# either. (2) "Sublimation" in the old MATERIAL_GATED_PROCESS_TYPES set is equally
# unreachable - "Sublimation" was never in AVAILABLE_PROCESSES or any process picker,
# so no ProcessInstance can ever have that process_type for the gating to apply to.
# Both were 100% inert in the app people actually use; omitting them here is a
# behavior-neutral cleanup of dead data, not a functional change - confirmed by
# grepping gui_components.py/sheet_experiment.py for both strings (no hits) before
# removing either.

AVAILABLE_PROCESSES = ["Experiment Info"] + sorted(k for k in PROCESSES if k != "Experiment Info")


# ---------------------------------------------------------------------------
# Excel_creator-facing API: field/group lookups for generate_steps_for_process
# ---------------------------------------------------------------------------


def _resolve_test(spec: dict, n: int | None = None):
    test = spec.get("test")
    if callable(test):
        return test(n)
    return test


def field_args(process_name: str, key: str, *, variant: str = "fields") -> tuple:
    """(key, test_value) ready for make_label(*field_args(...)) - looks up a single
    plain (non-indexed, non-optional) field. `variant` picks "fields" (the default) or
    "fields_ink_recycling" (Experiment Info's simplified variant)."""
    spec = PROCESSES[process_name][variant][key]
    return (key, _resolve_test(spec))


def optional_block_args(process_name: str, block_key: str) -> list[tuple]:
    """[(key, test_value), ...] for every field in one optional block (e.g. Spin
    Coating's "gasquenching"), in declared order - present only when the caller's own
    `config.get(block_key, False)` is True (that check stays in sheet_experiment.py,
    same as before; this just supplies the field data once the caller decides to
    include the block)."""
    block = PROCESSES[process_name]["optional"][block_key]
    return [(key, _resolve_test(spec)) for key, spec in block.items()]


def indexed_group_args(process_name: str, group_key: str, n: int) -> list[tuple]:
    """[(formatted_key, test_value), ...] for one iteration (1-based n) of an indexed
    group (e.g. Spin Coating's "solvents"), in declared order."""
    entries = PROCESSES[process_name]["indexed"][group_key]
    return [(entry["excel_key"].format(n=n), _resolve_test(entry, n)) for entry in entries]


def atmospheric_args() -> list[tuple]:
    """[(key, test_value), ...] for the atmospheric block appended to any real process
    (not Experiment Info) when its "add_atmospheric" config flag is on."""
    return [(key, _resolve_test(spec)) for key, spec in _ATMOSPHERIC_FIELDS.items()]


# ---------------------------------------------------------------------------
# smart_databaser-facing API: archive field-path lookups, replacing
# config/field_mappings.json's load_field_mappings/load_indexed_config_keys/
# load_field_value_multipliers
# ---------------------------------------------------------------------------


def _field_paths(spec: dict) -> list | None:
    if "paths" in spec:
        return spec["paths"]
    if "path" in spec:
        return [spec["path"]]
    return None


def _resolve_indexed_path(path_template: list, index0: int) -> list:
    return [index0 if segment == "{i}" else segment for segment in path_template]


def build_field_paths(
    processes: dict | None = None,
) -> dict[str, dict[str, tuple[list[list], bool]]]:
    """{process_type: {excel_field_key: (paths, unit_verified)}} - same shape
    data_manager.load_field_mappings() used to build from field_mappings.json. A field
    with neither "path" nor "paths" (deliberately unmapped, e.g. Datetime/Operator/
    Notes) is simply absent here, same as before. Pass `processes` to build from a
    different PROCESSES-shaped dict (e.g. a small synthetic one in a test) instead of
    the real module-level PROCESSES."""
    result: dict[str, dict[str, tuple[list[list], bool]]] = {}
    for process_type, spec in (processes if processes is not None else PROCESSES).items():
        field_paths: dict[str, tuple[list[list], bool]] = {}
        for key, field_spec in spec.get("fields", {}).items():
            paths = _field_paths(field_spec)
            if paths is not None:
                field_paths[key] = (paths, field_spec.get("unit_verified", True))
        for block in spec.get("optional", {}).values():
            for key, field_spec in block.items():
                paths = _field_paths(field_spec)
                if paths is not None:
                    field_paths[key] = (paths, field_spec.get("unit_verified", True))
        for group in spec.get("indexed", {}).values():
            for entry in group:
                start, end = entry.get("mapping_range", (1, 5))
                templates = entry.get("path_templates") or (
                    [entry["path"]] if "path" in entry else None
                )
                if templates is None:
                    continue
                for n in range(start, end + 1):
                    excel_key = entry["excel_key"].format(n=n)
                    field_paths[excel_key] = (
                        [_resolve_indexed_path(t, n - 1) for t in templates],
                        entry.get("unit_verified", True),
                    )
        result[process_type] = field_paths
    return result


def build_indexed_config_keys(processes: dict | None = None) -> dict[str, dict[str, str]]:
    """{process_type: {config_key: excel_key_template}} - same shape
    data_manager.load_indexed_config_keys() used to build, used by
    infer_config_from_source_step to widen a target process's config to match how much
    data a source batch step actually has. Only considers entries that actually carry a
    "path"/"path_templates" - matches the original's coupling (field_mappings.json's
    indexed_fields entries always had a path_template by construction), so a process
    with no archive-path data at all (e.g. Ink Recycling) correctly yields nothing here,
    same as before this module existed (Ink Recycling was never even a key in the old
    field_mappings.json). Pass `processes` to build from a different PROCESSES-shaped
    dict instead of the real module-level PROCESSES."""
    result: dict[str, dict[str, str]] = {}
    for process_type, spec in (processes if processes is not None else PROCESSES).items():
        mapping = {}
        for group_key, group in spec.get("indexed", {}).items():
            for entry in group:
                has_path = "path" in entry or "path_templates" in entry
                if has_path and entry.get("config_key") == group_key:
                    mapping[group_key] = entry["excel_key"]
                    break
        if mapping:
            result[process_type] = mapping
    return result


def build_field_value_multipliers(processes: dict | None = None) -> dict[str, dict[str, float]]:
    """{process_type: {excel_field_key: multiplier}} - same shape
    data_manager.load_field_value_multipliers() used to build. Pass `processes` to
    build from a different PROCESSES-shaped dict instead of the real module-level
    PROCESSES."""
    result: dict[str, dict[str, float]] = {}
    for process_type, spec in (processes if processes is not None else PROCESSES).items():
        multipliers: dict[str, float] = {}
        for key, field_spec in spec.get("fields", {}).items():
            if "multiply" in field_spec:
                multipliers[key] = field_spec["multiply"]
        for block in spec.get("optional", {}).values():
            for key, field_spec in block.items():
                if "multiply" in field_spec:
                    multipliers[key] = field_spec["multiply"]
        for group in spec.get("indexed", {}).values():
            for entry in group:
                if "multiply" not in entry:
                    continue
                start, end = entry.get("mapping_range", (1, 5))
                for n in range(start, end + 1):
                    multipliers[entry["excel_key"].format(n=n)] = entry["multiply"]
        if multipliers:
            result[process_type] = multipliers
    return result


# ---------------------------------------------------------------------------
# data_manager.py-facing API: the six former hand-maintained process-type lists
# ---------------------------------------------------------------------------


def build_configurable_process_types() -> set[str]:
    return {
        p
        for p, spec in PROCESSES.items()
        if spec["meta"]["numeric_config"] or spec["meta"]["boolean_config"]
    }


def build_material_gated_process_types() -> set[str]:
    return {p for p, spec in PROCESSES.items() if spec["meta"]["material_gated"]}


def build_default_config_by_process_type() -> dict[str, dict]:
    return {
        p: dict(spec["meta"]["config_defaults"])
        for p, spec in PROCESSES.items()
        if spec["meta"].get("config_defaults")
    }


def build_numeric_config_fields() -> list[tuple[str, str, set[str], int, int]]:
    """[(config_key, label, applicable_process_types, min, max), ...] - same shape
    data_manager.NUMERIC_CONFIG_FIELDS used to be hand-maintained as. Grouped from each
    process's own declared numeric_config entries; a (key, label, min, max) combination
    is assumed identical everywhere it's declared (true for every current process
    type - solvents/solutes are always (0, 20), spinsteps always (1, 5), etc.)."""
    grouped: dict[tuple[str, str, int, int], set[str]] = {}
    for process_type, spec in PROCESSES.items():
        for key, label, min_val, max_val in spec["meta"]["numeric_config"]:
            grouped.setdefault((key, label, min_val, max_val), set()).add(process_type)
    return [(key, label, types, mn, mx) for (key, label, mn, mx), types in grouped.items()]


def build_boolean_config_fields() -> list[tuple[str, str, set[str]]]:
    """[(config_key, label, applicable_process_types), ...] - same shape
    data_manager.BOOLEAN_CONFIG_FIELDS used to be hand-maintained as."""
    grouped: dict[tuple[str, str], set[str]] = {}
    for process_type, spec in PROCESSES.items():
        for key, label in spec["meta"]["boolean_config"]:
            grouped.setdefault((key, label), set()).add(process_type)
    return [(key, label, types) for (key, label), types in grouped.items()]
