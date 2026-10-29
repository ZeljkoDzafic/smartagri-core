"""Typed records for the core decision model. Everything is JSON-serialisable via to_dict()."""
from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Origin(str, Enum):
    MEASURED = "measured"
    USER_REPORTED = "user_reported"
    MODELED = "modeled"
    DERIVED = "derived"
    UNKNOWN = "unknown"


class Reliability(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    MISSING = "missing"
    # A present input of a variant without the q layer: its value is used as it is, but it carries no grade.
    # Never produced when q is on; never shown as "high".
    UNGRADED = "ungraded"

    @property
    def rank(self) -> int:
        # UNGRADED ranks like a value taken at face value: no layer that compares ranks (sigma, the q-aware
        # parts of pi) runs without q, so the rank is never used to grade it.
        return {"missing": 0, "low": 1, "medium": 2, "high": 3, "ungraded": 3}[self.value]


class Applicability(str, Enum):
    APPLICABLE = "applicable"
    CONDITIONAL = "conditional"
    NOT_APPLICABLE = "not_applicable"


class Sufficiency(str, Enum):
    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"

    @property
    def rank(self) -> int:
        return {"insufficient": 0, "partial": 1, "sufficient": 2}[self.value]


class Act(str, Enum):
    RECOMMEND = "recommend"
    CONDITIONAL = "conditional"
    ASK = "ask"
    ABSTAIN = "abstain"


class AdviceType(str, Enum):
    IRRIGATION_TIMING = "irrigation_timing"
    IRRIGATION_AMOUNT = "irrigation_amount"
    FERTILIZATION_PLAN = "fertilization_plan"
    FERTILIZATION_TIMING = "fertilization_timing"
    FIELD_OPS_WINDOW = "field_ops_window"
    SCOUTING = "scouting"
    OUT_OF_SCOPE = "out_of_scope"


def to_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ].*)?$")


def parse_date(value: Any) -> Optional[date]:
    """The calendar date of `value`, or None when it is absent or is not an ISO date (never raises). A string must start
    with YYYY-MM-DD: the compact form (20260425) is read by Python 3.11+ but not by 3.9, and a result that depends on the
    interpreter is not reproducible."""
    if isinstance(value, str) and not _ISO_DAY.match(value.strip()):
        return None
    if value is not None and not isinstance(value, (str, date, datetime)):
        return None
    try:
        return to_date(value.strip() if isinstance(value, str) else value)
    except (ValueError, TypeError):
        return None


# Inputs a person or a device reports AT a moment: they cannot be dated after the decision moment.
REPORT_DATE_FIELDS = ("bbch_reported_on", "soil_water_reported_on", "soil_moisture_measured_on", "last_irrigation_date",
                      "manure_date")
ALL_DATE_FIELDS = ("sowing_date",) + REPORT_DATE_FIELDS


def check_dates(d: Dict[str, Any], as_of: Optional[datetime]) -> None:
    """Raise ValueError for a malformed date, or a reported date after the decision moment, in a scenario's context.

    A planned sowing date may lie after the decision moment (nothing is sown yet); every other date of the agronomic
    record, the forecast issue time and the dated lists (soil analysis, observations, fertilisation records) describes
    something that already happened or was already issued, so it cannot be later than `as_of`. A scenario file is an
    authoring artefact: such an error is reported with the field name, never silently repaired. Granularity is the
    calendar day (as in the quality profile); a forecast issue time with a clock time is compared exactly when `as_of`
    has one too and both are naive or both aware."""
    a = d.get("A") or {}
    day = as_of.date() if as_of is not None else None

    def one(label: str, value: Any, future_ok: bool = False) -> None:
        if value is None or value == "":
            return
        parsed = parse_date(value)
        if parsed is None:
            raise ValueError("%s is not an ISO date: %r" % (label, value))
        if day is not None and parsed > day and not future_ok:
            raise ValueError("%s (%s) is dated after the decision time (%s)" % (label, value, day.isoformat()))

    for name in ALL_DATE_FIELDS:
        one("A." + name, a.get(name), future_ok=name == "sowing_date")
    if isinstance(a.get("soil_analysis"), dict):
        one("A.soil_analysis.date", a["soil_analysis"].get("date"))
    for i, o in enumerate(a.get("observations") or []):
        one("A.observations[%d].date" % i, o.get("date") if isinstance(o, dict) else None)
    for i, r in enumerate(a.get("fertilization_records") or []):
        one("A.fertilization_records[%d].date" % i, r.get("date") if isinstance(r, dict) else None)
    issued = (d.get("W") or {}).get("forecast_issued_at")
    one("W.forecast_issued_at", issued)
    if issued and as_of is not None:
        try:
            moment = datetime.fromisoformat(str(issued))
        except ValueError:
            return
        if (moment.tzinfo is None) == (as_of.tzinfo is None) and moment > as_of:
            raise ValueError("W.forecast_issued_at (%s) is dated after the decision time (%s)" % (issued, as_of.isoformat()))


def _plain(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_plain(v) for v in obj]
    return obj


class Record:
    def to_dict(self) -> Dict[str, Any]:
        return _plain(self)


# ---------------------------------------------------------------- context C = (P, A, W, S, Q)

@dataclass
class ParcelInfo(Record):
    parcel_id: str = "parcel"
    area_ha: Optional[float] = None
    centroid_lat: Optional[float] = None
    centroid_lon: Optional[float] = None
    region_class: Optional[str] = None


@dataclass
class Agronomic(Record):
    crop: str = "maize"
    sowing_date: Optional[str] = None
    bbch: Optional[int] = None
    bbch_origin: str = "user_reported"
    bbch_reported_on: Optional[str] = None
    irrigation_available: str = "unknown"          # yes | no | unknown
    irrigation_system_type: Optional[str] = None   # sprinkler | drip | furrow
    irrigation_efficiency: Optional[float] = None
    soil_texture: Optional[str] = None
    soil_awc_mm_m: Optional[float] = None
    soil_water_status: Optional[str] = None        # dry | moist | wet
    soil_water_origin: str = "user_reported"
    soil_water_reported_on: Optional[str] = None
    soil_moisture_vwc: Optional[float] = None      # sensor reading, if any
    soil_moisture_measured_on: Optional[str] = None
    soil_analysis: Optional[Dict[str, Any]] = None  # {"date": "...", "level": low|medium|high, ...}
    # None = unknown, [] = none applied, list of {n_kg_ha: ...}, or a class: none | partial | full
    previous_fertilization: Optional[Any] = None
    yield_target_t_ha: Optional[float] = None
    operation: Optional[str] = None
    user_observations: List[str] = field(default_factory=list)
    # Optional inputs. Each is used only where a rule in config/rules.yaml says how.
    irrigation_capacity_mm_day: Optional[float] = None
    last_irrigation_date: Optional[str] = None
    last_irrigation_mm: Optional[float] = None
    fertilization_records: Optional[List[Dict[str, Any]]] = None   # [{date, product, rate_kg_ha, n_kg_ha?}]
    previous_crop: Optional[str] = None            # maize | wheat | soybean | sunflower | alfalfa | other
    manure_t_ha: Optional[float] = None
    manure_date: Optional[str] = None
    hybrid_fao: Optional[int] = None               # maturity group, 200-700
    plant_density_ha: Optional[float] = None
    observations: Optional[List[Dict[str, Any]]] = None   # [{date, kind, note}]


@dataclass
class WeatherSummary(Record):
    origin: str = "modeled"
    precip_past_7d_mm: Optional[float] = None
    precip_past_30d_mm: Optional[float] = None
    et0_past_7d_mm: Optional[float] = None
    gdd_since_sowing: Optional[float] = None
    precip_forecast_3d_mm: Optional[float] = None
    precip_forecast_7d_mm: Optional[float] = None
    precip_prob_3d: Optional[float] = None
    tmin_forecast_7d_c: Optional[float] = None
    tmax_forecast_7d_c: Optional[float] = None
    wind_forecast_max_ms: Optional[float] = None
    forecast_issued_at: Optional[str] = None
    horizon_days: int = 0


@dataclass
class NdviObservation(Record):
    obs_date: str = ""
    median: Optional[float] = None
    p10: Optional[float] = None
    p90: Optional[float] = None
    usable_share: float = 0.0              # = valid_px_ratio: usable pixels / pixels considered, in [0, 1]
    # Optional quality metadata (parcel_features, docs/parcel-features.md). None = not reported; an observation that
    # carries none of them is graded exactly as before.
    cloud_px_share: Optional[float] = None     # share of the interior pixels masked as cloud, in [0, 1]
    shadow_px_share: Optional[float] = None    # share masked as cloud shadow, in [0, 1]
    cloud_flag: Optional[bool] = None          # a cloud or shadow (after dilation) touches or lies in the parcel
    interior_buffer_m: Optional[float] = None  # metres removed from the boundary before the statistics
    n_px_total: Optional[int] = None
    n_px_interior: Optional[int] = None
    n_px_valid: Optional[int] = None
    mixed_px_share: Optional[float] = None     # share of the parcel's pixels that are boundary (mixed) pixels
    temporal_outlier: Optional[bool] = None    # screened out by the producer's multi-temporal check
    mask_layers: Optional[List[str]] = None    # masks applied, e.g. ["scl", "cloud_probability", "dilation"]


@dataclass
class ParcelFeatures(Record):
    """A validated `parcel_features` document (schema_version 1) from an external parcel feature provider.

    Built only by `core.parcel_features.parse`, which checks the contract, the decision moment and, when the
    geometry is known, its hash. The producer's own hashes travel with it as data."""
    schema_version: int = 1
    parcel_id: str = ""
    geometry_sha256: str = ""
    as_of: str = ""
    computed_at: str = ""
    source_obs_dates: List[str] = field(default_factory=list)
    producer: Dict[str, Any] = field(default_factory=dict)
    ndvi_observations: List[NdviObservation] = field(default_factory=list)
    stage_estimate: Optional[Dict[str, Any]] = None
    crop_plausibility: Optional[Dict[str, Any]] = None
    events: Optional[Dict[str, Any]] = None
    document_sha256: str = ""                  # sha256 of the canonical JSON of the document as received


@dataclass
class SatelliteSummary(Record):
    ndvi_series: List[NdviObservation] = field(default_factory=list)
    scene_ids: List[str] = field(default_factory=list)
    # Inside S on purpose: the ablation that removes the satellite context removes the features with it.
    parcel_features: Optional[ParcelFeatures] = None


@dataclass
class Question(Record):
    text: str = ""
    advice_type: AdviceType = AdviceType.SCOUTING
    # Conditions an LLM extracted from the question text only (used by the condition-aware baseline).
    stated_conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Context(Record):
    P: ParcelInfo = field(default_factory=ParcelInfo)
    A: Agronomic = field(default_factory=Agronomic)
    W: WeatherSummary = field(default_factory=WeatherSummary)
    S: SatelliteSummary = field(default_factory=SatelliteSummary)
    Q: Question = field(default_factory=Question)
    as_of: Optional[datetime] = None
    questions_asked: int = 0
    declined_inputs: List[str] = field(default_factory=list)   # inputs the user said they cannot supply
    # Free questions of a model (variants without the sufficiency layer) the user could not answer: the question texts.
    declined_free: List[str] = field(default_factory=list)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Context":
        s = dict(d.get("S") or {})
        s["ndvi_series"] = [NdviObservation(**o) for o in s.get("ndvi_series", [])]
        q = dict(d.get("Q") or {})
        q["advice_type"] = AdviceType(q.get("advice_type", "scouting"))
        as_of = d.get("as_of")
        if as_of is not None and not isinstance(as_of, datetime):
            as_of = datetime.fromisoformat(str(as_of))
        check_dates(d, as_of)
        if s.get("parcel_features") is not None:
            # A scenario file is an authoring artefact: a features block that breaks the contract (or the decision
            # moment) is an error, never silently dropped. The provider path rejects instead (providers/parcel_features).
            from .parcel_features import merge_ndvi, parse
            pf = s["parcel_features"]
            pf = pf if isinstance(pf, ParcelFeatures) else parse(
                pf, as_of=as_of, parcel_id=(d.get("P") or {}).get("parcel_id"))
            s["parcel_features"] = pf
            s["ndvi_series"] = merge_ndvi(s["ndvi_series"], pf)
        return Context(
            P=ParcelInfo(**(d.get("P") or {})),
            A=Agronomic(**(d.get("A") or {})),
            W=WeatherSummary(**(d.get("W") or {})),
            S=SatelliteSummary(**s),
            Q=Question(**q),
            as_of=as_of,
            questions_asked=int(d.get("questions_asked", 0)),
            declined_inputs=list(d.get("declined_inputs", [])),
            declined_free=list(d.get("declined_free", [])),
        )


# ---------------------------------------------------------------- quality profile q

@dataclass
class Observation(Record):
    """Raw view of one input before grading."""
    value: Any = None
    origin: Origin = Origin.UNKNOWN
    age_days: Optional[float] = None
    coverage: Optional[float] = None
    count: Optional[int] = None
    source_ref: str = ""
    # Facts the grading rules may only use to LOWER a grade (NDVI quality fields, a stage conflict); None = none.
    detail: Optional[Dict[str, Any]] = None
    # True when the input is one that must carry the date or time it was reported or measured and does not: its age is
    # then unknown (age_days None), which is never the same as "fresh" (audit D1).
    date_unknown: bool = False
    # The reason the value cannot be right (core/plausibility.py), or None. Such an input is graded low and is never
    # handed to the decision cores or the tools (core/quality.values) (audit D3).
    implausible: Optional[str] = None


@dataclass
class Quality(Record):
    input: str
    origin: Origin
    age_days: Optional[float]
    coverage: Optional[float]
    reliability: Reliability
    basis: str = ""
    source_ref: str = ""
    # What lowered the grade or what the grade rests on beyond (origin, age, coverage): NDVI quality fields, the
    # stage conflict. Recorded in the run's decisions (provenance). None when there is nothing to add.
    detail: Optional[Dict[str, Any]] = None


QualityProfile = Dict[str, Quality]


# ---------------------------------------------------------------- corpus passages

@dataclass
class PassageMeta(Record):
    crop: Optional[List[str]] = None
    bbch_min: Optional[int] = None
    bbch_max: Optional[int] = None
    advice_types: Optional[List[str]] = None
    region_scope: Optional[List[str]] = None
    irrigated: Optional[bool] = None        # True = written for irrigated production only
    rainfed: Optional[bool] = None          # True = written for rainfed (non-irrigated) production only
    soil_scope: Optional[List[str]] = None  # soil textures the passage is written for (vocab.yaml)
    valid_from: Optional[str] = None        # ISO date from which the passage holds (e.g. a regulation)
    valid_until: Optional[str] = None
    source_type: Optional[str] = None
    claims_numeric: Optional[bool] = None   # the passage states numbers (doses, norms); read by grounding
    requires_no_rain_3d: bool = False
    conditions_text: List[str] = field(default_factory=list)
    # What the passage recommends, as {decision key: value}, e.g. {"irrigation_at_flowering": "irrigate"}.
    # Two passages with the same key and different values conflict.
    recommends: Optional[Dict[str, str]] = None


@dataclass
class Passage(Record):
    id: str
    document_id: str = ""
    text: str = ""
    meta: PassageMeta = field(default_factory=PassageMeta)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Passage":
        return Passage(id=d["id"], document_id=d.get("document_id", ""), text=d.get("text", ""),
                       meta=PassageMeta(**(d.get("meta") or {})))


# ---------------------------------------------------------------- results

@dataclass
class ApplicabilityResult(Record):
    passage_id: str
    status: Applicability
    unmet: List[str] = field(default_factory=list)
    unverifiable: List[str] = field(default_factory=list)
    hard_fail: Optional[str] = None


@dataclass
class SufficiencyResult(Record):
    advice_type: AdviceType
    status: Sufficiency
    missing: List[Any] = field(default_factory=list)   # input names or {"one_of": [...]}
    degraded_to: Optional[AdviceType] = None
    corpus_insufficient: bool = False

    def missing_inputs(self) -> List[str]:
        out: List[str] = []
        for m in self.missing:
            names = m["one_of"] if isinstance(m, dict) else [m]
            for n in names:
                if n not in out:
                    out.append(n)
        return out


@dataclass
class QuestionCandidate(Record):
    input: str
    sensitivity: int
    cost: int
    outcomes: List[str] = field(default_factory=list)
    user_obtainable: bool = True


@dataclass
class QuestionChoice(Record):
    input: Optional[str] = None
    text: str = ""
    how_to_obtain: str = ""
    candidates: List[QuestionCandidate] = field(default_factory=list)
    reason: str = ""


@dataclass
class PolicyDecision(Record):
    act: Optional[Act]
    reason_code: str
    allow_quantity: bool = False
    warnings: List[str] = field(default_factory=list)


@dataclass
class ToolResult(Record):
    tool: str
    inputs: Dict[str, Any]
    output: Optional[Dict[str, Any]]
    formula: str = ""
    source_ref: str = ""
    reason: Optional[str] = None


@dataclass
class VariantConfig(Record):
    name: str = ""
    retrieval: str = "hybrid"                 # none | hybrid
    applicability: str = "off"                # off | query_conditions | parcel_conditions
    dynamic_context: bool = False
    quality: bool = False
    sufficiency: bool = False
    asking: bool = False
    policy: bool = False
    grounding: bool = False


@dataclass
class SourceConflict(Record):
    key: str
    values: Dict[str, List[str]]          # recommended value -> passage ids
    resolution: str                       # prefer_applicable | degrade | report
    preferred_value: Optional[str] = None


@dataclass
class Decision(Record):
    variant: str
    advice_type: AdviceType
    quality: Dict[str, Quality]
    applicability: List[ApplicabilityResult]
    passage_budget: List[str]
    sufficiency: Optional[SufficiencyResult]
    question: Optional[QuestionChoice]
    policy: PolicyDecision
    core_action: Optional[str]
    tools: List[ToolResult]
    config_hashes: Dict[str, str]
    conflicts: List["SourceConflict"] = field(default_factory=list)
    # Conflicts between INPUTS (not passages): e.g. the stage the user gave against the satellite stage estimate.
    # Read from the quality profile; they already lowered the grade, this is the evidence.
    input_conflicts: List[Dict[str, Any]] = field(default_factory=list)
