"""
Data Loader Module

Provides low-level data loading functions for retrieving sample metadata and
measurements from NOMAD OASIS API endpoints.

Key Responsibilities:
    - Load process step metadata (spin coating, evaporation, etc.)
    - Load measurement results (JV, EQE, MPP tracking, etc.)
    - Handle API authentication and pagination
    - Parse NOMAD data structures

Classes:
    HySprintDataLoader: Low-level API interface

Author: HySprint Team
"""

import logging
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class HySprintDataLoader:
    """
    A class to load and process different types of HySprint measurement data.

    Categories:
    - Metadata: Process information (cleaning, evaporation, coating, etc.)
    - Results: Measurement results (JV, EQE, SEM, etc.)
    """

    # Define measurement categories
    METADATA_TYPES = [
        "HySprint_Cleaning",
        "HySprint_Substrate",
        "HySprint_Evaporation",
        "HySprint_SlotDieCoating",
        "HySprint_SpinCoating",
        "HySprint_Inkjet_Printing",
    ]

    RESULT_TYPES = [
        "HySprint_JVmeasurement",
        "HySprint_EQEmeasurement",
        "HySprint_SimpleMPPTracking",
        "HySprint_SEM",
        "HySprint_AbsPLMeasurement",
        "HySprint_XRD_XY",
    ]

    def __init__(self, url: str, token: str, get_all_data_func):
        """
        Initialize the data loader.

        Args:
            url: API base URL
            token: Authentication token
            get_all_data_func: Function to fetch data from API (e.g., get_all_ijp)
        """
        self.url = url
        self.token = token
        self.get_all_data = get_all_data_func

    # METADATA LOADERS

    def load_inkjet_printing_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load Inkjet Printing metadata."""
        logger.info("Fetching Inkjet Printing data for %d samples", len(sample_ids))

        all_ijp = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_Inkjet_Printing"
        )

        if not all_ijp:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_ijp.items():
            logger.debug("Processing sample: %s", sample_id)

            for entry in sample_entries:
                ijp_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": ijp_data.get("name", ""),
                    "datetime": ijp_data.get("datetime", ""),
                    "description": ijp_data.get("description", ""),
                    "location": ijp_data.get("location", ""),
                    "position_in_plan": ijp_data.get("positon_in_experimental_plan", None),
                }

                # Annealing information
                annealing = ijp_data.get("annealing", {})
                row_data.update(
                    {
                        "annealing_temperature": annealing.get("temperature", None),
                        "annealing_time": annealing.get("time", None),
                        "annealing_atmosphere": annealing.get("atmosphere", ""),
                    }
                )

                # Atmosphere information
                atmosphere = ijp_data.get("atmosphere", {})
                row_data.update(
                    {
                        "relative_humidity": atmosphere.get("relative_humidity", None),
                    }
                )

                # Printing properties
                properties = ijp_data.get("properties", {})
                row_data.update(
                    {
                        "cartridge_pressure": properties.get("cartridge_pressure", None),
                        "drop_density": properties.get("drop_density", None),
                        "printed_area": properties.get("printed_area", None),
                        "substrate_temperature": properties.get("substrate_temperature", None),
                    }
                )

                # Print head properties
                print_head = properties.get("print_head_properties", {})
                row_data.update(
                    {
                        "print_head_name": print_head.get("print_head_name", ""),
                        "print_head_temperature": print_head.get("print_head_temperature", None),
                        "num_active_nozzles": print_head.get(
                            "number_of_active_print_nozzles", None
                        ),
                        "nozzle_drop_frequency": print_head.get(
                            "print_nozzle_drop_frequency", None
                        ),
                        "nozzle_drop_volume": print_head.get("print_nozzle_drop_volume", None),
                    }
                )

                # Extract layer information
                layers = ijp_data.get("layer", [])
                if layers:
                    layer = layers[0]
                    row_data.update(
                        {
                            "layer_material": layer.get("layer_material", ""),
                            "layer_material_name": layer.get("layer_material_name", ""),
                            "layer_type": layer.get("layer_type", ""),
                        }
                    )

                # Extract solution information
                solutions = ijp_data.get("solution", [])
                if solutions:
                    solution = solutions[0]
                    solution_details = solution.get("solution_details", {})

                    # Solvent information
                    solvents = solution_details.get("solvent", [])
                    for i, solvent in enumerate(solvents):
                        solvent_name = solvent.get("chemical_2", {}).get("name", f"solvent{i + 1}")
                        row_data.update(
                            {
                                f"solvent_amount_{solvent_name}": solvent.get(
                                    "amount_relative", None
                                ),
                                f"solvent_volume_{solvent_name}": solvent.get(
                                    "chemical_volume", None
                                ),
                            }
                        )

                    # Solute information
                    solutes = solution_details.get("solute", [])
                    for i, solute in enumerate(solutes):
                        solute_name = solute.get("chemical_2", {}).get("name", f"solute{i + 1}")
                        row_data.update(
                            {
                                f"solute_concentration_{solute_name}": solute.get(
                                    "concentration_mol", None
                                )
                            }
                        )

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_cleaning_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load Cleaning process metadata."""
        logger.info("Fetching Cleaning data for %d samples", len(sample_ids))

        all_cleaning = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_Cleaning"
        )

        if not all_cleaning:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_cleaning.items():
            for entry in sample_entries:
                cleaning_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": cleaning_data.get("name", ""),
                    "description": cleaning_data.get("description", ""),
                    "location": cleaning_data.get("location", ""),
                    "position_in_plan": cleaning_data.get("positon_in_experimental_plan", None),
                }

                # Cleaning steps
                cleaning_steps = cleaning_data.get("cleaning", [])
                for i, step in enumerate(cleaning_steps):
                    solvent_name = step.get("solvent_2", {}).get("name", f"step{i + 1}")
                    row_data.update(
                        {
                            f"cleaning_time_{solvent_name}": step.get("time", None),
                            f"cleaning_temperature_{solvent_name}": step.get("temperature", None),
                        }
                    )

                # UV cleaning
                uv_cleaning = cleaning_data.get("cleaning_uv", [])
                if uv_cleaning:
                    row_data["uv_cleaning_time"] = uv_cleaning[0].get("time", None)

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_substrate_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load Substrate information."""
        logger.info("Fetching Substrate data for %d samples", len(sample_ids))

        all_substrate = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_Substrate"
        )

        if not all_substrate:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_substrate.items():
            for entry in sample_entries:
                substrate_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": substrate_data.get("name", ""),
                    "lab_id": substrate_data.get("lab_id", ""),
                    "description": substrate_data.get("description", ""),
                    "solar_cell_area": substrate_data.get("solar_cell_area", None),
                    "number_of_pixels": substrate_data.get("number_of_pixels", None),
                    "pixel_area": substrate_data.get("pixel_area", None),
                    "substrate": substrate_data.get("substrate", ""),
                }

                # Conducting materials
                conducting_materials = substrate_data.get("conducting_material", [])
                if conducting_materials:
                    row_data["conducting_material"] = ", ".join(conducting_materials)

                # Substrate properties
                substrate_props = substrate_data.get("substrate_properties", [])
                for i, prop in enumerate(substrate_props):
                    row_data.update(
                        {
                            f"substrate_layer_type_{i + 1}": prop.get("layer_type", ""),
                            f"substrate_layer_material_{i + 1}": prop.get(
                                "layer_material_name", ""
                            ),
                        }
                    )

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_evaporation_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load Evaporation process metadata."""
        logger.info("Fetching Evaporation data for %d samples", len(sample_ids))

        all_evap = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_Evaporation"
        )

        if not all_evap:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_evap.items():
            for entry in sample_entries:
                evap_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": evap_data.get("name", ""),
                    "description": evap_data.get("description", ""),
                    "location": evap_data.get("location", ""),
                    "position_in_plan": evap_data.get("positon_in_experimental_plan", None),
                    "co_evaporation": evap_data.get("co_evaporation", False),
                }

                # Layer information
                layers = evap_data.get("layer", [])
                if layers:
                    layer = layers[0]
                    row_data.update(
                        {
                            "layer_type": layer.get("layer_type", ""),
                            "layer_material_name": layer.get("layer_material_name", ""),
                        }
                    )

                # Organic evaporation details
                organic_evap = evap_data.get("organic_evaporation", [])
                if organic_evap:
                    evap = organic_evap[0]
                    row_data.update(
                        {
                            "thickness": evap.get("thickness", None),
                            "pressure": evap.get("pressure", None),
                            "pressure_start": evap.get("pressure_start", None),
                            "pressure_end": evap.get("pressure_end", None),
                            "start_rate": evap.get("start_rate", None),
                            "target_rate": evap.get("target_rate", None),
                            "substrate_temperature": evap.get("substrate_temparature", None),
                            "evap_material": evap.get("chemical_2", {}).get("name", ""),
                        }
                    )

                    temperatures = evap.get("temparature", [])
                    if temperatures:
                        row_data["temperature_min"] = min(temperatures)
                        row_data["temperature_max"] = max(temperatures)

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_slot_die_coating_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load Slot Die Coating process metadata."""
        logger.info("Fetching Slot Die Coating data for %d samples", len(sample_ids))

        all_sdc = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_SlotDieCoating"
        )

        if not all_sdc:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_sdc.items():
            for entry in sample_entries:
                sdc_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": sdc_data.get("name", ""),
                    "location": sdc_data.get("location", ""),
                    "position_in_plan": sdc_data.get("positon_in_experimental_plan", None),
                }

                # Layer information
                layers = sdc_data.get("layer", [])
                if layers:
                    layer = layers[0]
                    row_data.update(
                        {
                            "layer_type": layer.get("layer_type", ""),
                            "layer_material_name": layer.get("layer_material_name", ""),
                        }
                    )

                # Solution information
                solutions = sdc_data.get("solution", [])
                if solutions:
                    solution = solutions[0]
                    solution_details = solution.get("solution_details", {})

                    # Solute information
                    solutes = solution_details.get("solute", [])
                    for i, solute in enumerate(solutes):
                        solute_name = solute.get("chemical_2", {}).get("name", f"solute{i + 1}")
                        row_data[f"solute_concentration_{solute_name}"] = solute.get(
                            "concentration_mol", None
                        )

                    # Solvent information
                    solvents = solution_details.get("solvent", [])
                    for i, solvent in enumerate(solvents):
                        solvent_name = solvent.get("chemical_2", {}).get("name", f"solvent{i + 1}")
                        row_data[f"solvent_{solvent_name}"] = True

                # Annealing information
                annealing = sdc_data.get("annealing", {})
                row_data.update(
                    {
                        "annealing_temperature": annealing.get("temperature", None),
                        "annealing_time": annealing.get("time", None),
                        "annealing_atmosphere": annealing.get("atmosphere", ""),
                    }
                )

                # Process properties
                properties = sdc_data.get("properties", {})
                row_data.update(
                    {
                        "flow_rate": properties.get("flow_rate", None),
                        "slot_die_head_distance": properties.get(
                            "slot_die_head_distance_to_thinfilm", None
                        ),
                        "slot_die_head_speed": properties.get("slot_die_head_speed", None),
                    }
                )

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_spin_coating_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load Spin Coating process metadata."""
        logger.info("Fetching Spin Coating data for %d samples", len(sample_ids))

        all_spin = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_SpinCoating"
        )

        if not all_spin:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_spin.items():
            for entry in sample_entries:
                spin_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": spin_data.get("name", ""),
                    "description": spin_data.get("description", ""),
                    "location": spin_data.get("location", ""),
                    "position_in_plan": spin_data.get("positon_in_experimental_plan", None),
                }

                # Layer information
                layers = spin_data.get("layer", [])
                if layers:
                    layer = layers[0]
                    row_data.update(
                        {
                            "layer_type": layer.get("layer_type", ""),
                            "layer_material_name": layer.get("layer_material_name", ""),
                        }
                    )

                # Solution information
                solutions = spin_data.get("solution", [])
                if solutions:
                    solution = solutions[0]
                    row_data["solution_volume"] = solution.get("solution_volume", None)

                    solution_details = solution.get("solution_details", {})

                    # Solute information
                    solutes = solution_details.get("solute", [])
                    for i, solute in enumerate(solutes):
                        solute_name = solute.get("chemical_2", {}).get("name", f"solute{i + 1}")
                        row_data[f"solute_{solute_name}"] = True

                    # Solvent information
                    solvents = solution_details.get("solvent", [])
                    for i, solvent in enumerate(solvents):
                        solvent_name = solvent.get("chemical_2", {}).get("name", f"solvent{i + 1}")
                        row_data.update(
                            {
                                f"solvent_amount_{solvent_name}": solvent.get(
                                    "amount_relative", None
                                ),
                            }
                        )

                # Annealing information
                annealing = spin_data.get("annealing", {})
                row_data.update(
                    {
                        "annealing_temperature": annealing.get("temperature", None),
                        "annealing_time": annealing.get("time", None),
                        "annealing_atmosphere": annealing.get("atmosphere", ""),
                    }
                )

                # Quenching information
                quenching = spin_data.get("quenching", {})
                if quenching:
                    row_data.update(
                        {
                            "quenching_type": quenching.get("m_def", "").split(".")[-1]
                            if "m_def" in quenching
                            else "",
                            "anti_solvent_volume": quenching.get("anti_solvent_volume", None),
                            "anti_solvent_dropping_time": quenching.get(
                                "anti_solvent_dropping_time", None
                            ),
                            "anti_solvent": quenching.get("anti_solvent_2", {}).get("name", ""),
                        }
                    )

                # Recipe steps
                recipe_steps = spin_data.get("recipe_steps", [])
                for i, step in enumerate(recipe_steps):
                    row_data.update(
                        {
                            f"step_{i + 1}_time": step.get("time", None),
                            f"step_{i + 1}_speed": step.get("speed", None),
                            f"step_{i + 1}_acceleration": step.get("acceleration", None),
                        }
                    )

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    # RESULT LOADERS

    def load_jv_measurement_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load JV measurement results."""
        logger.info("Fetching JV measurement data for %d samples", len(sample_ids))

        all_jv = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_JVmeasurement"
        )

        if not all_jv:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_jv.items():
            for entry in sample_entries:
                jv_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": jv_data.get("name", ""),
                    "datetime": jv_data.get("datetime", ""),
                    "description": jv_data.get("description", ""),
                    "data_file": jv_data.get("data_file", ""),
                }

                # Initialize JV parameter lists
                jv_params = [
                    "efficiency",
                    "open_circuit_voltage",
                    "fill_factor",
                    "short_circuit_current_density",
                    "series_resistance",
                    "shunt_resistance",
                ]

                for param in jv_params:
                    row_data[param] = []

                # Extract JV curve data
                jv_curves = jv_data.get("jv_curve", [])
                for curve in jv_curves:
                    for param in jv_params:
                        if param in curve:
                            row_data[param].append(curve[param])

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_eqe_measurement_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load EQE measurement results."""
        logger.info("Fetching EQE measurement data for %d samples", len(sample_ids))

        all_eqe = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_EQEmeasurement"
        )

        if not all_eqe:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_eqe.items():
            for entry in sample_entries:
                eqe_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": eqe_data.get("name", ""),
                    "datetime": eqe_data.get("datetime", ""),
                    "description": eqe_data.get("description", ""),
                    "data_file": eqe_data.get("data_file", ""),
                }

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_mpp_tracking_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load MPP Tracking results."""
        logger.info("Fetching MPP Tracking data for %d samples", len(sample_ids))

        all_mpp = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_SimpleMPPTracking"
        )

        if not all_mpp:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_mpp.items():
            for entry in sample_entries:
                mpp_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": mpp_data.get("name", ""),
                    "datetime": mpp_data.get("datetime", ""),
                    "description": mpp_data.get("description", ""),
                    "data_file": mpp_data.get("data_file", ""),
                }

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_sem_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load SEM measurement results."""
        logger.info("Fetching SEM data for %d samples", len(sample_ids))

        all_sem = self.get_all_data(self.url, self.token, sample_ids, eqe_type="HySprint_SEM")

        if not all_sem:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_sem.items():
            for entry in sample_entries:
                sem_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": sem_data.get("name", ""),
                    "datetime": sem_data.get("datetime", ""),
                    "description": sem_data.get("description", ""),
                }

                # Detector data files
                detector_data = sem_data.get("detector_data", [])
                if detector_data:
                    row_data["detector_files"] = ", ".join(detector_data)
                    row_data["num_detector_files"] = len(detector_data)

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_abspl_measurement_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load Absorption/PL measurement results."""
        logger.info("Fetching AbsPL measurement data for %d samples", len(sample_ids))

        all_abspl = self.get_all_data(
            self.url, self.token, sample_ids, eqe_type="HySprint_AbsPLMeasurement"
        )

        if not all_abspl:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_abspl.items():
            for entry in sample_entries:
                abspl_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": abspl_data.get("name", ""),
                    "datetime": abspl_data.get("datetime", ""),
                    "description": abspl_data.get("description", ""),
                    "data_file": abspl_data.get("data_file", ""),
                }

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    def load_xrd_data(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Optional[pd.DataFrame]:
        """Load XRD measurement results."""
        logger.info("Fetching XRD data for %d samples", len(sample_ids))

        all_xrd = self.get_all_data(self.url, self.token, sample_ids, eqe_type="HySprint_XRD_XY")

        if not all_xrd:
            return None

        sample_data_list = []

        for sample_id, sample_entries in all_xrd.items():
            for entry in sample_entries:
                xrd_data = entry[0]

                row_data = {
                    "sample_id": sample_id,
                    "variation": variation.get(sample_id, ""),
                    "name": xrd_data.get("name", ""),
                    "datetime": xrd_data.get("datetime", ""),
                    "description": xrd_data.get("description", ""),
                    "data_file": xrd_data.get("data_file", ""),
                }

                sample_data_list.append(pd.DataFrame([row_data]))

        return pd.concat(sample_data_list, ignore_index=True) if sample_data_list else None

    # UTILITY METHODS

    def get_available_metadata_types(self, sample_ids: List[str]) -> List[str]:
        """Get available metadata measurement types for given samples."""
        available_types = []
        for measurement_type in self.METADATA_TYPES:
            data = self.get_all_data(self.url, self.token, sample_ids, eqe_type=measurement_type)
            if data:
                available_types.append(measurement_type)
        return available_types

    def get_available_result_types(self, sample_ids: List[str]) -> List[str]:
        """Get available result measurement types for given samples."""
        available_types = []
        for measurement_type in self.RESULT_TYPES:
            data = self.get_all_data(self.url, self.token, sample_ids, eqe_type=measurement_type)
            if data:
                available_types.append(measurement_type)
        return available_types

    def load_all_metadata(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Dict[str, pd.DataFrame]:
        """Load all available metadata for given samples."""
        metadata_dict = {}

        # Load each type of metadata
        metadata_loaders = {
            "inkjet_printing": self.load_inkjet_printing_data,
            "cleaning": self.load_cleaning_data,
            "substrate": self.load_substrate_data,
            "evaporation": self.load_evaporation_data,
            "slot_die_coating": self.load_slot_die_coating_data,
            "spin_coating": self.load_spin_coating_data,
        }

        for name, loader_func in metadata_loaders.items():
            try:
                data = loader_func(sample_ids, variation)
                if data is not None and not data.empty:
                    metadata_dict[name] = data
                    logger.info("Loaded %s data: %d entries", name, len(data))
            except Exception as e:
                logger.error("Error loading %s data: %s", name, e)

        return metadata_dict

    def load_all_results(
        self, sample_ids: List[str], variation: Dict[str, str]
    ) -> Dict[str, pd.DataFrame]:
        """Load all available results for given samples."""
        results_dict = {}

        # Load each type of result
        result_loaders = {
            "jv_measurement": self.load_jv_measurement_data,
            "eqe_measurement": self.load_eqe_measurement_data,
            "mpp_tracking": self.load_mpp_tracking_data,
            "sem": self.load_sem_data,
            "abspl_measurement": self.load_abspl_measurement_data,
            "xrd": self.load_xrd_data,
        }

        for name, loader_func in result_loaders.items():
            try:
                data = loader_func(sample_ids, variation)
                if data is not None and not data.empty:
                    results_dict[name] = data
                    logger.info("Loaded %s data: %d entries", name, len(data))
            except Exception as e:
                logger.error("Error loading %s data: %s", name, e)

        return results_dict

    def merge_metadata_with_results(
        self, metadata_dict: Dict[str, pd.DataFrame], results_dict: Dict[str, pd.DataFrame]
    ) -> Dict[str, pd.DataFrame]:
        """Merge metadata with results based on sample_id."""
        merged_dict = {}

        # Create a combined metadata DataFrame
        if metadata_dict:
            # Start with the first metadata type as base
            base_metadata = None
            for meta_name, meta_df in metadata_dict.items():
                if base_metadata is None:
                    base_metadata = meta_df.copy()
                else:
                    # Merge with existing metadata on sample_id
                    base_metadata = pd.merge(
                        base_metadata,
                        meta_df,
                        on="sample_id",
                        how="outer",
                        suffixes=("", f"_{meta_name}"),
                    )

            # Now merge each result type with the combined metadata
            for result_name, result_df in results_dict.items():
                if base_metadata is not None:
                    merged_df = pd.merge(
                        base_metadata,
                        result_df,
                        on="sample_id",
                        how="outer",
                        suffixes=("_meta", "_result"),
                    )
                    merged_dict[result_name] = merged_df
                else:
                    merged_dict[result_name] = result_df
        else:
            merged_dict = results_dict

        return merged_dict

    def create_summary_table(self, sample_ids: List[str]) -> pd.DataFrame:
        """Create a summary table showing available data types for each sample."""
        summary_data = []

        for sample_id in sample_ids:
            row = {"sample_id": sample_id}

            # Check metadata types
            for meta_type in self.METADATA_TYPES:
                try:
                    data = self.get_all_data(self.url, self.token, [sample_id], eqe_type=meta_type)
                    row[f"{meta_type}_available"] = bool(data and sample_id in data)
                except Exception:
                    row[f"{meta_type}_available"] = False

            # Check result types
            for result_type in self.RESULT_TYPES:
                try:
                    data = self.get_all_data(
                        self.url, self.token, [sample_id], eqe_type=result_type
                    )
                    row[f"{result_type}_available"] = bool(data and sample_id in data)
                except Exception:
                    row[f"{result_type}_available"] = False

            summary_data.append(row)

        return pd.DataFrame(summary_data)


# Convenience functions for backward compatibility
def load_ijp_data_legacy(
    url: str, token: str, get_all_data_func, sample_ids: List[str], variation: Dict[str, str]
) -> Optional[pd.DataFrame]:
    """
    Legacy function that combines inkjet printing and JV measurement data
    similar to the original get_ijp_data function.
    """
    loader = HySprintDataLoader(url, token, get_all_data_func)

    # Load inkjet printing metadata
    ijp_data = loader.load_inkjet_printing_data(sample_ids, variation)

    # Load JV measurement results
    jv_data = loader.load_jv_measurement_data(sample_ids, variation)

    if ijp_data is None and jv_data is None:
        return None

    if ijp_data is None:
        return jv_data

    if jv_data is None:
        return ijp_data

    # Merge the two datasets on sample_id
    merged_data = pd.merge(ijp_data, jv_data, on="sample_id", how="outer", suffixes=("_ijp", "_jv"))

    return merged_data


# Example usage and helper functions
def example_usage():
    """
    Example of how to use the HySprintDataLoader class.
    """

    # Load specific data types

    # Load all metadata

    # Load all results

    # Create merged datasets

    # Create summary table

    pass


if __name__ == "__main__":
    logger.info("HySprint Data Loader - Modular data loading for HySprint measurements")
    logger.info("Available metadata types: %s", HySprintDataLoader.METADATA_TYPES)
    logger.info("Available result types: %s", HySprintDataLoader.RESULT_TYPES)
