"""
Sampling Algorithms for the Design of Experiments application.
Implementation of all DoE sampling algorithms with quality metrics.

Every generate() returns a DataFrame with one column per variable. Anything the
user should know about the design (the actual run count of a fixed-size
design, a subsampled grid, an unbalanced level) is appended to
df.attrs["notes"] (see add_note / get_notes) and shown in the app, instead of
a warnings.warn that nobody sees.
"""

import itertools
import logging
import warnings
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from data_manager import Variable, VariableType
from scipy.spatial.distance import cdist, pdist
from scipy.stats import qmc
from utils import ValidationUtils

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

# Exponent of the Morris-Mitchell criterion used by maximin_selection.
MAXIMIN_PHI_POWER = 15
# Designs whose run count is fixed by their construction, not by n_samples.
FIXED_SIZE_DESIGNS = ("Orthogonal Arrays", "Definitive Screening Design")
# Runs per variable usually wanted to fit a model to the results (e.g. a
# Gaussian process for Bayesian optimization; Loeppky et al. 2009).
RUNS_PER_VARIABLE_FOR_MODELLING = 10


def add_note(df: pd.DataFrame, text: str) -> pd.DataFrame:
    """Attach a user-facing note to a generated design."""
    df.attrs.setdefault("notes", []).append(text)
    return df


def get_notes(df: pd.DataFrame) -> List[str]:
    return list(df.attrs.get("notes", []))


def _levels(var: Variable) -> list:
    """The values a discrete or categorical variable can take."""
    return var.categories if var.type == VariableType.CATEGORICAL else var.get_discrete_values()


def _continuous_from_unit(u, var: Variable) -> np.ndarray:
    """Map [0, 1] to the variable's range, evenly in log10 space for log-scale
    variables (min > 0 is checked when the variable is defined)."""
    u = np.asarray(u, dtype=float)
    if getattr(var, "log_scale", False):
        lo, hi = np.log10(var.min_value), np.log10(var.max_value)
        return 10.0 ** (lo + u * (hi - lo))
    return var.min_value + u * (var.max_value - var.min_value)


def _from_unit(u, var: Variable) -> list:
    """Map unit-interval draws to variable values: continuous scaled into its
    range, discrete/categorical by equal-width bins over the levels."""
    if var.type == VariableType.CONTINUOUS:
        return list(_continuous_from_unit(u, var))
    levels = _levels(var)
    index = np.clip((np.asarray(u) * len(levels)).astype(int), 0, len(levels) - 1)
    return [levels[i] for i in index]


def _frame(unit_samples: np.ndarray, variables: List[Variable]) -> pd.DataFrame:
    return pd.DataFrame(
        {var.name: _from_unit(unit_samples[:, i], var) for i, var in enumerate(variables)}
    )


def _center_value(var: Variable, index: int = 0):
    """Centre of a variable's range: the midpoint (geometric for log scale), the
    level nearest it for a discrete variable, and for a categorical variable
    (which has no centre) its categories in turn."""
    if var.type == VariableType.CATEGORICAL:
        return var.categories[index % len(var.categories)]
    mid = float(_continuous_from_unit(0.5, var))
    if var.type == VariableType.DISCRETE:
        levels = np.asarray(var.get_discrete_values(), dtype=float)
        return float(levels[np.argmin(np.abs(levels - mid))])
    return mid


def design_space(data: pd.DataFrame, variables: List[Variable]) -> np.ndarray:
    """Points in a common space for distances: numeric variables scaled to [0, 1]
    over their defined range (log10 for log scale), categorical variables one-hot
    divided by sqrt(2), so any two different categories are exactly 1 apart
    (a mismatch, as in Gower distance) instead of being treated as ordered codes."""
    blocks = []
    for var in variables:
        values = data[var.name]
        if var.type == VariableType.CATEGORICAL:
            onehot = values.astype(str).to_numpy()[:, None] == np.array(var.categories)[None, :]
            blocks.append(onehot.astype(float) / np.sqrt(2))
            continue
        x = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        lo, hi = var.min_value, var.max_value
        if getattr(var, "log_scale", False):
            x, lo, hi = np.log10(x), np.log10(lo), np.log10(hi)
        blocks.append(((x - lo) / ((hi - lo) or 1.0))[:, None])
    return np.hstack(blocks)


class SamplingAlgorithm(ABC):
    """Abstract base class for sampling algorithms."""

    def __init__(self, name: str, description: str, requires_libraries: List[str] = None):
        self.name = name
        self.description = description
        self.requires_libraries = requires_libraries or []

    @abstractmethod
    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Generate samples for given variables."""
        pass

    def is_available(self) -> bool:
        """Check if the algorithm is available (dependencies satisfied)."""
        return True  # Override in subclasses that require specific libraries

    def get_parameters(self) -> Dict[str, Any]:
        """Get algorithm-specific parameters and their default values."""
        return {}


def _balance_levels(unit_samples: np.ndarray, variables: List[Variable]) -> np.ndarray:
    """For discrete/categorical columns, reassign levels by rank so every level
    occurs floor(n/L) or ceil(n/L) times, while keeping the LHS's ordering of
    points. Equal-width binning of the LHS strata can otherwise miss a level or
    double another when n is not a multiple of the level count."""
    u = unit_samples.copy()
    n = len(u)
    for i, var in enumerate(variables):
        if var.type == VariableType.CONTINUOUS:
            continue
        n_levels = len(_levels(var))
        ranks = np.argsort(np.argsort(u[:, i]))
        u[:, i] = (np.floor(ranks * n_levels / n) + 0.5) / n_levels
    return u


class LatinHypercubeSampling(SamplingAlgorithm):
    """Latin Hypercube Sampling implementation."""

    def __init__(self):
        super().__init__(
            name="Latin Hypercube Sampling",
            description="Space-filling design with one sample in each row and column projection",
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Generate LHS samples."""
        optimization = kwargs.get("optimization", None)
        sampler = qmc.LatinHypercube(d=len(variables), seed=random_state, optimization=optimization)
        unit_samples = _balance_levels(sampler.random(n=n_samples), variables)
        return _frame(unit_samples, variables)

    def get_parameters(self) -> Dict[str, Any]:
        """Get LHS-specific parameters."""
        return {
            "optimization": {
                "type": "select",
                "options": [None, "random-cd", "lloyd"],
                "default": None,
                "description": "Optimization method for LHS",
            }
        }


class SobolSampling(SamplingAlgorithm):
    """Sobol sequence sampling implementation."""

    def __init__(self):
        super().__init__(
            name="Sobol Sequences",
            description=(
                "Low-discrepancy quasi-random sequences with excellent space-filling properties"
            ),
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Generate Sobol sequence samples."""
        scramble = kwargs.get("scramble", True)
        sampler = qmc.Sobol(d=len(variables), scramble=scramble, seed=random_state)
        with warnings.catch_warnings():
            # scipy warns about non-power-of-2 counts; reported as a note instead.
            warnings.simplefilter("ignore")
            unit_samples = sampler.random(n=n_samples)
        df = _frame(unit_samples, variables)
        if n_samples & (n_samples - 1):
            lower = 1 << (n_samples.bit_length() - 1)
            add_note(
                df,
                f"Sobol points are evenly balanced only for a power-of-2 count; {n_samples} "
                f"is not (nearest: {lower} or {lower * 2}).",
            )
        return df

    def get_parameters(self) -> Dict[str, Any]:
        """Get Sobol-specific parameters."""
        return {
            "scramble": {
                "type": "boolean",
                "default": True,
                "description": "Apply Owen scrambling to improve randomization",
            }
        }


class HaltonSampling(SamplingAlgorithm):
    """Halton sequence sampling implementation."""

    def __init__(self):
        super().__init__(
            name="Halton Sequences",
            description="Quasi-random sequences with good space-filling properties",
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Generate Halton sequence samples."""
        scramble = kwargs.get("scramble", True)
        sampler = qmc.Halton(d=len(variables), scramble=scramble, seed=random_state)

        # Skip initial samples to avoid low-discrepancy issues
        skip_samples = kwargs.get("skip_samples", 100)
        if skip_samples > 0:
            _ = sampler.random(n=skip_samples)

        return _frame(sampler.random(n=n_samples), variables)

    def get_parameters(self) -> Dict[str, Any]:
        """Get Halton-specific parameters."""
        return {
            "scramble": {
                "type": "boolean",
                "default": True,
                "description": "Apply scrambling to improve randomization",
            },
            "skip_samples": {
                "type": "integer",
                "default": 100,
                "min": 0,
                "max": 1000,
                "description": "Number of initial samples to skip",
            },
        }


class RandomSampling(SamplingAlgorithm):
    """Simple random sampling implementation."""

    def __init__(self):
        super().__init__(
            name="Random Sampling", description="Simple random sampling for baseline comparison"
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Generate random samples."""
        rng = np.random.RandomState(random_state)
        columns = {}
        for var in variables:
            if var.type == VariableType.CONTINUOUS:
                columns[var.name] = _continuous_from_unit(rng.uniform(0, 1, n_samples), var)
            else:
                levels = _levels(var)
                columns[var.name] = [levels[i] for i in rng.randint(0, len(levels), n_samples)]
        return pd.DataFrame(columns)


class UniformGridSampling(SamplingAlgorithm):
    """Uniform grid sampling implementation."""

    def __init__(self):
        super().__init__(
            name="Uniform Grid Sampling",
            description="Regular grid sampling for systematic coverage",
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Generate uniform grid samples."""
        n_dims = len(variables)
        samples_per_dim = int(np.ceil(n_samples ** (1 / n_dims)))

        grid_points = []
        for var in variables:
            if var.type == VariableType.CONTINUOUS:
                points = list(_continuous_from_unit(np.linspace(0, 1, samples_per_dim), var))
            elif var.type == VariableType.DISCRETE:
                discrete_values = var.get_discrete_values()
                indices = np.linspace(0, len(discrete_values) - 1, samples_per_dim).astype(int)
                points = [discrete_values[i] for i in indices]
            else:
                points = (var.categories * (samples_per_dim // len(var.categories) + 1))[
                    :samples_per_dim
                ]
            grid_points.append(points)

        grid = list(itertools.product(*grid_points))
        df = pd.DataFrame(grid, columns=[var.name for var in variables])

        if len(df) > n_samples:
            rng = np.random.RandomState(random_state)
            indices = rng.choice(len(df), n_samples, replace=False)
            full = len(df)
            df = df.iloc[np.sort(indices)].reset_index(drop=True)
            add_note(
                df,
                f"The full grid has {full} points ({samples_per_dim} per variable); a random "
                f"subset of {n_samples} is used, so the result is no longer a regular grid. "
                f"Use {samples_per_dim**n_dims} samples for the full grid, or "
                f"{(samples_per_dim - 1) ** n_dims} for a coarser one.",
            )
        return df


_OA_PRIMES = (2, 3, 5, 7)


def orthogonal_array(p: int, n_factors: int) -> np.ndarray:
    """Strength-2 orthogonal array with p levels (p prime): runs are all vectors
    x of GF(p)^k, one column per projective point c of GF(p)^k (first nonzero
    entry 1), holding x . c mod p. Any two such columns are linearly
    independent, so every pair of levels occurs equally often in every pair of
    columns. k is the smallest with (p^k - 1) / (p - 1) >= n_factors columns:
    L4/L8/L16 for 2 levels, L9/L27 for 3, L25 for 5, L49 for 7.
    Returns an array of shape (p^k, n_factors) with entries 0..p-1."""
    k = 2
    while (p**k - 1) // (p - 1) < n_factors:
        k += 1
    runs = np.array(list(itertools.product(range(p), repeat=k)))
    columns = [
        c
        for c in itertools.product(range(p), repeat=k)
        if any(c) and c[next(i for i, v in enumerate(c) if v)] == 1
    ]
    return (runs @ np.array(columns).T % p)[:, :n_factors]


class OrthogonalArraySampling(SamplingAlgorithm):
    """Orthogonal Array sampling implementation."""

    def __init__(self):
        super().__init__(
            name="Orthogonal Arrays",
            description="Classical DoE approach excellent for screening experiments",
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """A real strength-2 orthogonal array (see orthogonal_array). Its size is
        fixed by the number of variables and levels, so n_samples is not used;
        the actual run count is reported in a note. A variable with fewer levels
        than the array uses collapsed levels (still orthogonal, not equally
        frequent). Raises ValueError rather than silently falling back to random
        sampling when no array fits."""
        continuous_levels = int(kwargs.get("continuous_levels", 3))
        counts = [
            continuous_levels if var.type == VariableType.CONTINUOUS else len(_levels(var))
            for var in variables
        ]
        p = next((q for q in _OA_PRIMES if q >= max(counts)), None)
        if p is None:
            widest = variables[int(np.argmax(counts))]
            raise ValueError(
                f"Orthogonal arrays here support up to {_OA_PRIMES[-1]} levels per variable; "
                f"'{widest.name}' has {max(counts)}. Use fewer levels (a larger step or fewer "
                "categories) or another design."
            )

        array = orthogonal_array(p, len(variables))
        columns = {}
        collapsed = []
        for i, var in enumerate(variables):
            if var.type == VariableType.CONTINUOUS:
                columns[var.name] = list(_continuous_from_unit(array[:, i] / (p - 1), var))
                continue
            levels = _levels(var)
            if len(levels) < p:
                collapsed.append(f"{var.name} ({len(levels)})")
            columns[var.name] = [levels[a % len(levels)] for a in array[:, i]]
        df = pd.DataFrame(columns)

        add_note(
            df,
            f"Orthogonal array with {len(df)} runs for {len(variables)} variable(s) at "
            f"{p} levels: every pair of levels of every two variables appears equally "
            f"often. Its size is fixed by the design, so the requested {n_samples} "
            "samples is not used.",
        )
        if any(var.type == VariableType.CONTINUOUS for var in variables) and (
            p != continuous_levels
        ):
            add_note(
                df,
                f"Continuous variables use {p} levels to match the array "
                f"({continuous_levels} were requested).",
            )
        if collapsed:
            add_note(
                df,
                f"Fewer levels than the array's {p}: {', '.join(collapsed)}. Their levels "
                "are reused (collapsed), which keeps the array orthogonal but makes some "
                "levels more frequent than others.",
            )
        return df

    def get_parameters(self) -> Dict[str, Any]:
        """Get Orthogonal Array specific parameters."""
        return {
            "continuous_levels": {
                "type": "select",
                "options": list(_OA_PRIMES),
                "default": 3,
                "description": "Number of levels for continuous variables",
            }
        }


# Paley conference matrices exist for order q + 1 with q prime.
_CONFERENCE_PRIMES = (3, 5, 7, 11, 13, 17, 19, 23)


def conference_matrix(order: int) -> np.ndarray:
    """Paley conference matrix C of the given order (order - 1 prime): zero
    diagonal, +-1 elsewhere, C C^T = (order - 1) I. Symmetric when
    order - 1 = 1 mod 4, antisymmetric when 3 mod 4."""
    q = order - 1
    residues = {(x * x) % q for x in range(1, q)}

    def chi(x: int) -> int:
        x %= q
        return 0 if x == 0 else (1 if x in residues else -1)

    C = np.zeros((order, order), dtype=int)
    C[0, 1:] = 1
    C[1:, 0] = 1 if q % 4 == 1 else -1
    C[1:, 1:] = [[chi(j - i) for j in range(q)] for i in range(q)]
    return C


class DefinitiveScreeningDesign(SamplingAlgorithm):
    """Definitive screening design (Jones & Nachtsheim 2011)."""

    def __init__(self):
        super().__init__(
            name="Definitive Screening Design",
            description="Three-level screening: main effects free of two-factor interactions",
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Fold-over of a conference matrix C plus a centre run: rows of C, of
        -C and one all-zero row, levels -1/0/+1 mapped to min/centre/max. With m
        numeric variables this needs about 2m + 1 runs (main effects are
        unaffected by any two-factor interaction, and every variable has a
        centre level, so curvature shows). Numeric variables only."""
        categorical = [v.name for v in variables if v.type == VariableType.CATEGORICAL]
        if categorical:
            raise ValueError(
                "Definitive screening designs need numeric variables; categorical: "
                f"{', '.join(categorical)}. Use an orthogonal array instead."
            )
        m = len(variables)
        order = next((q + 1 for q in _CONFERENCE_PRIMES if q + 1 >= max(m, 4)), None)
        if order is None:
            raise ValueError(
                f"Definitive screening designs here support up to {_CONFERENCE_PRIMES[-1] + 1} "
                f"variables ({m} given)."
            )
        C = conference_matrix(order)
        coded = np.vstack([C, -C, np.zeros((1, order), dtype=int)])[:, :m]

        columns = {}
        for i, var in enumerate(variables):
            low = float(_continuous_from_unit(0.0, var))
            high = float(_continuous_from_unit(1.0, var))
            if var.type == VariableType.DISCRETE:
                levels = var.get_discrete_values()
                low, high = levels[0], levels[-1]
            center = _center_value(var)
            columns[var.name] = [low if c < 0 else high if c > 0 else center for c in coded[:, i]]
        df = pd.DataFrame(columns)
        add_note(
            df,
            f"Definitive screening design: {len(df)} runs for {m} variable(s) (a conference "
            f"matrix of order {order}, folded over, plus one centre run). Its size is fixed "
            f"by the design, so the requested {n_samples} samples is not used.",
        )
        return df


def maximin_selection(
    candidates: np.ndarray,
    n_samples: int,
    max_iterations: int = 100,
    random_state: Optional[int] = None,
    fixed: Optional[np.ndarray] = None,
) -> List[int]:
    """Pick n_samples rows of candidates maximizing the smallest distance between
    any two picks, and between a pick and any fixed point (an existing design
    being augmented). Start: farthest-point (each next pick is the candidate
    farthest from the picks so far and the fixed points; the first is random,
    or the one farthest from the fixed points). Then an exchange search: for
    each pick in turn, swap in the candidate that most improves the minimum
    distance (Morris-Mitchell form, vectorized over all candidates); stop
    when a full sweep changes nothing. The farthest-point start keeps the
    exchange out of the poor local optima a random start often ends in."""
    n_candidates = len(candidates)
    if n_samples >= n_candidates:
        return list(range(n_candidates))

    rng = np.random.RandomState(random_state)
    to_fixed = (
        cdist(candidates, fixed).min(axis=1)
        if fixed is not None and len(fixed)
        else np.full(n_candidates, np.inf)
    )
    nearest_pick = to_fixed.copy()
    first = int(np.argmax(to_fixed)) if np.isfinite(to_fixed).any() else rng.randint(n_candidates)
    selected = [first]
    for _ in range(n_samples - 1):
        nearest_pick = np.minimum(nearest_pick, cdist(candidates, candidates[[selected[-1]]])[:, 0])
        nearest_pick[selected] = -np.inf
        selected.append(int(np.argmax(nearest_pick)))
    selected = np.array(selected)
    to_selected = cdist(candidates, candidates[selected])  # (n_candidates, n_samples)

    # Exchange on the Morris-Mitchell criterion sum(d^-p): for large p it ranks
    # designs like the minimum distance does, but it also rewards moving pairs
    # other than the closest one, so the search does not stall on plateaus
    # where several pairs share the minimum.
    power = MAXIMIN_PHI_POWER
    with np.errstate(divide="ignore"):
        fixed_term = (
            (cdist(candidates, fixed) ** -power).sum(axis=1)
            if fixed is not None and len(fixed)
            else np.zeros(n_candidates)
        )
        for _ in range(max_iterations):
            improved = False
            for i in range(n_samples):
                others = np.delete(np.arange(n_samples), i)
                cost = fixed_term + (to_selected[:, others] ** -power).sum(axis=1)
                current = cost[selected[i]]
                cost[selected] = np.inf
                best = int(np.argmin(cost))
                if cost[best] < current * (1 - 1e-9):
                    selected[i] = best
                    to_selected[:, i] = cdist(candidates, candidates[[best]])[:, 0]
                    improved = True
            if not improved:
                break
    return list(selected)


class MaximinDistanceSampling(SamplingAlgorithm):
    """Maximin distance design implementation."""

    def __init__(self):
        super().__init__(
            name="Maximin Distance Design",
            description="Optimizes minimum distance between sample points",
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """Generate maximin distance samples from an LHS candidate set."""
        max_iterations = kwargs.get("max_iterations", 100)
        n_candidates = kwargs.get("n_candidates") or max(n_samples * 10, 200)
        candidates = LatinHypercubeSampling().generate(variables, n_candidates, random_state)
        selected = maximin_selection(
            design_space(candidates, variables), n_samples, max_iterations, random_state
        )
        return candidates.iloc[selected].reset_index(drop=True)

    def get_parameters(self) -> Dict[str, Any]:
        """Get Maximin-specific parameters."""
        return {
            "max_iterations": {
                "type": "integer",
                "default": 100,
                "min": 10,
                "max": 1000,
                "description": "Maximum optimization iterations",
            },
            "n_candidates": {
                "type": "integer",
                "default": None,  # max(n_samples * 10, 200)
                "min": 100,
                "max": 10000,
                "description": "Number of candidate samples to generate",
            },
        }


class AugmentDesign(SamplingAlgorithm):
    """Add runs to an existing design."""

    def __init__(self):
        super().__init__(
            name="Augment Existing Design",
            description="Adds runs to an existing design, as far as possible from its points",
        )

    def generate(
        self,
        variables: List[Variable],
        n_samples: int,
        random_state: Optional[int] = None,
        existing: Optional[pd.DataFrame] = None,
        **kwargs,
    ) -> pd.DataFrame:
        """n_samples new runs chosen by maximin from an LHS candidate set, with
        the existing design's points held fixed: new runs fill the gaps the
        existing ones leave instead of starting from scratch (e.g. the next
        round after a first design or a set of BO suggestions). Returns the new
        runs only."""
        if existing is None or len(existing) == 0:
            raise ValueError(
                "Upload the existing design first (a CSV with one column per variable)."
            )
        missing = [v.name for v in variables if v.name not in existing.columns]
        if missing:
            raise ValueError(f"The existing design has no column for: {', '.join(missing)}.")
        existing = existing[[v.name for v in variables]].dropna()
        n_candidates = max(n_samples * 20, 500)
        candidates = LatinHypercubeSampling().generate(variables, n_candidates, random_state)
        selected = maximin_selection(
            design_space(candidates, variables),
            n_samples,
            kwargs.get("max_iterations", 100),
            random_state,
            fixed=design_space(existing, variables),
        )
        df = candidates.iloc[selected].reset_index(drop=True)
        add_note(
            df,
            f"{len(df)} new runs added to the {len(existing)} existing ones, placed as far "
            "as possible from them and from each other. The table lists the new runs only.",
        )
        return df


class SamplingEngine:
    """Main engine for managing sampling algorithms and quality metrics."""

    def __init__(self):
        """Initialize the sampling engine with all available algorithms."""
        self.algorithms = {
            "Latin Hypercube Sampling": LatinHypercubeSampling(),
            "Sobol Sequences": SobolSampling(),
            "Halton Sequences": HaltonSampling(),
            "Random Sampling": RandomSampling(),
            "Uniform Grid Sampling": UniformGridSampling(),
            "Orthogonal Arrays": OrthogonalArraySampling(),
            "Definitive Screening Design": DefinitiveScreeningDesign(),
            "Maximin Distance Design": MaximinDistanceSampling(),
            "Augment Existing Design": AugmentDesign(),
        }

        # Filter out unavailable algorithms
        self.available_algorithms = {
            name: alg for name, alg in self.algorithms.items() if alg.is_available()
        }

        self.validator = ValidationUtils()

    def get_available_algorithms(self) -> Dict[str, str]:
        """Get list of available algorithms with descriptions."""
        return {name: alg.description for name, alg in self.available_algorithms.items()}

    def get_algorithm_parameters(self, algorithm_name: str) -> Dict[str, Any]:
        """Get parameters for a specific algorithm."""
        if algorithm_name not in self.available_algorithms:
            return {}

        return self.available_algorithms[algorithm_name].get_parameters()

    def generate_samples(
        self,
        variables: List[Variable],
        algorithm: str,
        n_samples: int,
        random_state: Optional[int] = None,
        **algorithm_params,
    ) -> pd.DataFrame:
        """Generate samples using specified algorithm. Notes for the user are in
        the result's attrs (get_notes)."""
        if algorithm not in self.available_algorithms:
            raise ValueError(f"Algorithm '{algorithm}' is not available")

        if not variables:
            raise ValueError("No variables defined")

        if n_samples < 1:
            raise ValueError("Number of samples must be positive")

        sampler = self.available_algorithms[algorithm]
        samples = sampler.generate(variables, n_samples, random_state, **algorithm_params)

        recommended = RUNS_PER_VARIABLE_FOR_MODELLING * len(variables)
        if algorithm not in FIXED_SIZE_DESIGNS and len(samples) < recommended:
            add_note(
                samples,
                f"To fit a model to the results (e.g. Bayesian optimization in "
                f"Global_analyzer), about {RUNS_PER_VARIABLE_FOR_MODELLING} runs per "
                f"variable is a common rule of thumb: {recommended} here. Fewer is fine "
                "for a first screening.",
            )
        return samples

    def finalize_design(
        self,
        samples: pd.DataFrame,
        variables: List[Variable],
        n_center: int = 0,
        n_replicates: int = 1,
        n_blocks: int = 1,
        randomize: bool = False,
        random_state: Optional[int] = None,
    ) -> pd.DataFrame:
        """Turn a generated design into a run sheet.

        n_center: extra runs at the centre of every variable (pure error and a
            curvature check); categorical variables cycle through their categories.
        n_replicates: every run (design and centre) repeated this many times.
        n_blocks: runs split into this many blocks (e.g. one per day or
            precursor lot), each a random, near-equal share of the design points
            and of the centre points, so block differences can later be told
            apart from variable effects.
        randomize: random run order within each block, from random_state, so
            drift over time does not line up with a variable.

        Adds only the columns an option needs (point_type, replicate, block,
        run_order); with the defaults the design is returned unchanged.
        """
        notes = get_notes(samples)
        design = samples.copy()
        if n_center > 0:
            center = pd.DataFrame(
                [{var.name: _center_value(var, i) for var in variables} for i in range(n_center)]
            )
            design = pd.concat(
                [design.assign(point_type="design"), center.assign(point_type="centre")],
                ignore_index=True,
            )
            if any(v.type == VariableType.CATEGORICAL for v in variables):
                notes.append(
                    "Categorical variables have no centre; centre runs cycle through "
                    "their categories."
                )
        if n_replicates > 1:
            design = pd.concat(
                [design.assign(replicate=r + 1) for r in range(n_replicates)], ignore_index=True
            )

        rng = np.random.default_rng(random_state)
        if n_blocks > 1:
            block = np.empty(len(design), dtype=int)
            kinds = design["point_type"] if "point_type" in design else pd.Series("", design.index)
            offset = 0
            for kind in kinds.unique():
                idx = np.flatnonzero(kinds.to_numpy() == kind)
                order = rng.permutation(len(idx))
                block[idx[order]] = (np.arange(len(idx)) + offset) % n_blocks + 1
                offset += len(idx)
            design["block"] = block
            notes.append(
                f"{n_blocks} blocks: run each block in one go (one day, one precursor lot). "
                "Add the block as a categorical parameter in the analysis so that "
                "block-to-block differences are not mistaken for variable effects."
            )
        if randomize:
            design["_key"] = rng.random(len(design))
            sort_by = ["block", "_key"] if "block" in design else ["_key"]
            design = design.sort_values(sort_by, kind="stable").drop(columns="_key")
            design = design.reset_index(drop=True)
            design.insert(0, "run_order", np.arange(1, len(design) + 1))
            notes.append(
                f"Run order randomized (seed {random_state}); measure in the order of "
                "the run_order column."
            )
        elif "block" in design:
            design = design.sort_values("block", kind="stable").reset_index(drop=True)

        leading = [c for c in ("run_order", "block", "point_type", "replicate") if c in design]
        design = design[leading + [c for c in design.columns if c not in leading]]
        design.attrs["notes"] = notes
        return design

    def calculate_quality_metrics(
        self, samples: pd.DataFrame, variables: List[Variable]
    ) -> Dict[str, Any]:
        """Calculate quality metrics for generated samples."""
        if samples.empty:
            return {}

        # Remove experiment ID column for calculations
        data_cols = [var.name for var in variables]
        data = samples[data_cols]

        metrics = {}

        # Basic metrics
        metrics["sample_count"] = len(samples)
        metrics["variable_count"] = len(variables)

        # Space-filling metrics
        metrics.update(self._calculate_space_filling_metrics(data, variables))

        # Statistical properties
        metrics.update(self._calculate_statistical_metrics(data, variables))

        # Coverage metrics
        metrics.update(self._calculate_coverage_metrics(data, variables))

        return metrics

    def _calculate_space_filling_metrics(
        self, data: pd.DataFrame, variables: List[Variable]
    ) -> Dict[str, Any]:
        """Calculate space-filling quality metrics."""
        metrics = {}

        # Convert to numeric for distance calculations
        numeric_data = self._convert_to_numeric_for_metrics(data, variables)

        if numeric_data.size > 0:
            # Minimum distance
            if len(data) > 1:
                distances = pdist(numeric_data)
                metrics["min_distance"] = float(np.min(distances))
                metrics["mean_distance"] = float(np.mean(distances))
                metrics["max_distance"] = float(np.max(distances))

                # Distance uniformity (coefficient of variation)
                metrics["distance_uniformity"] = float(np.std(distances) / np.mean(distances))

            # Discrepancy (simplified calculation)
            metrics["star_discrepancy"] = self._calculate_star_discrepancy(numeric_data)

        return metrics

    def _calculate_statistical_metrics(
        self, data: pd.DataFrame, variables: List[Variable]
    ) -> Dict[str, Any]:
        """Calculate statistical quality metrics."""
        metrics = {}

        # Variable-wise statistics
        variable_stats = {}
        correlation_data = []

        for var in variables:
            if var.name in data.columns:
                col_data = data[var.name]

                if var.type in [VariableType.CONTINUOUS, VariableType.DISCRETE]:
                    numeric_data = pd.to_numeric(col_data, errors="coerce")
                    correlation_data.append(numeric_data)

                    var_stats = {
                        "mean": float(numeric_data.mean()),
                        "std": float(numeric_data.std()),
                        "min": float(numeric_data.min()),
                        "max": float(numeric_data.max()),
                        "range_coverage": self._calculate_range_coverage(numeric_data, var),
                    }

                elif var.type == VariableType.CATEGORICAL:
                    value_counts = col_data.value_counts()
                    var_stats = {
                        "unique_categories": len(value_counts),
                        "category_distribution": value_counts.to_dict(),
                        "uniformity": self._calculate_categorical_uniformity(value_counts),
                    }

                variable_stats[var.name] = var_stats

        metrics["variable_statistics"] = variable_stats

        # Correlation analysis for numeric variables
        if len(correlation_data) > 1:
            corr_matrix = np.corrcoef(correlation_data)

            # Extract upper triangle (excluding diagonal)
            upper_tri = corr_matrix[np.triu_indices_from(corr_matrix, k=1)]

            metrics["correlation_stats"] = {
                "max_correlation": float(np.max(np.abs(upper_tri))),
                "mean_correlation": float(np.mean(np.abs(upper_tri))),
                "correlation_matrix": corr_matrix.tolist(),
            }

        return metrics

    def _calculate_coverage_metrics(
        self, data: pd.DataFrame, variables: List[Variable]
    ) -> Dict[str, Any]:
        """Calculate coverage quality metrics."""
        metrics = {}

        total_coverage = 1.0
        coverage_details = {}

        for var in variables:
            if var.name not in data.columns:
                continue

            col_data = data[var.name]
            coverage = 1.0  # Initialize coverage variable

            if var.type == VariableType.CONTINUOUS:
                # Calculate range coverage
                numeric_data = pd.to_numeric(col_data, errors="coerce")
                data_min = numeric_data.min()
                data_max = numeric_data.max()
                data_range = data_max - data_min
                total_range = var.max_value - var.min_value
                coverage = (data_range / total_range) if total_range > 0 else 1.0

            elif var.type == VariableType.DISCRETE:
                # Calculate discrete value coverage
                possible_values = set(var.get_discrete_values())
                covered_values = set(col_data.unique())
                coverage = len(covered_values) / len(possible_values)

            elif var.type == VariableType.CATEGORICAL:
                # Calculate category coverage
                covered_categories = set(col_data.unique())
                total_categories = set(var.categories)
                coverage = len(covered_categories) / len(total_categories)

            coverage_details[var.name] = float(coverage)
            total_coverage *= coverage

        metrics["coverage_per_variable"] = coverage_details
        metrics["overall_coverage"] = float(total_coverage)

        return metrics

    def _convert_to_numeric_for_metrics(
        self, data: pd.DataFrame, variables: List[Variable]
    ) -> np.ndarray:
        """Convert data to numeric format for metric calculations."""
        numeric_data = np.zeros((len(data), len(variables)))

        for i, var in enumerate(variables):
            if var.name not in data.columns:
                continue

            col_data = data[var.name]

            if var.type == VariableType.CATEGORICAL:
                # Convert categories to numeric codes
                unique_vals = col_data.unique()
                val_to_num = {val: j for j, val in enumerate(unique_vals)}
                numeric_data[:, i] = [val_to_num[val] for val in col_data]
            else:
                numeric_data[:, i] = pd.to_numeric(col_data, errors="coerce")

        # Normalize to [0, 1] for consistent metrics
        for i in range(numeric_data.shape[1]):
            col_min, col_max = numeric_data[:, i].min(), numeric_data[:, i].max()
            if col_max > col_min:
                numeric_data[:, i] = (numeric_data[:, i] - col_min) / (col_max - col_min)

        return numeric_data

    def _calculate_star_discrepancy(self, points: np.ndarray) -> float:
        """Calculate star discrepancy (simplified version)."""
        if points.size == 0 or len(points) < 2:
            return 0.0

        n_points, n_dims = points.shape

        # Simplified discrepancy calculation
        # For each point, calculate the volume of the box from origin
        volumes = np.prod(points, axis=1)
        empirical_measure = np.mean(volumes)

        # Theoretical measure for uniform distribution
        theoretical_measure = 1.0 / (2**n_dims)

        return abs(empirical_measure - theoretical_measure)

    def _calculate_range_coverage(self, data: pd.Series, variable: Variable) -> float:
        """Calculate how well the data covers the variable's range."""
        if variable.type not in [VariableType.CONTINUOUS, VariableType.DISCRETE]:
            return 1.0

        data_min, data_max = data.min(), data.max()
        var_min, var_max = variable.min_value, variable.max_value

        if var_max == var_min:
            return 1.0

        return (data_max - data_min) / (var_max - var_min)

    def _calculate_categorical_uniformity(self, value_counts: pd.Series) -> float:
        """Calculate uniformity of categorical distribution."""
        if len(value_counts) <= 1:
            return 1.0

        # Calculate entropy-based uniformity
        probabilities = value_counts / value_counts.sum()
        entropy = -np.sum(probabilities * np.log2(probabilities))
        max_entropy = np.log2(len(value_counts))

        return entropy / max_entropy if max_entropy > 0 else 1.0

    def compare_algorithms(
        self,
        variables: List[Variable],
        n_samples: int,
        algorithms: List[str],
        random_state: Optional[int] = None,
    ) -> pd.DataFrame:
        """Compare multiple algorithms on the same problem."""
        results = []

        for algorithm in algorithms:
            if algorithm not in self.available_algorithms:
                continue

            try:
                # Generate samples
                samples = self.generate_samples(variables, algorithm, n_samples, random_state)

                # Calculate metrics
                metrics = self.calculate_quality_metrics(samples, variables)

                # Add algorithm name and compile results
                result = {"Algorithm": algorithm}
                result.update(metrics)
                results.append(result)

            except Exception as e:
                # Add failed algorithm with error info
                results.append({"Algorithm": algorithm, "Error": str(e)})

        return pd.DataFrame(results)
