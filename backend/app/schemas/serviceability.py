"""
Pydantic schemas for CAD Serviceability Assessment.
Milestone 2: Clearance, Obstruction, Dependency Graph, and Explainable Scoring.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple
from pydantic import BaseModel, Field


# ─── Clearance Schemas ────────────────────────────────────────────────────────

class Point3D(BaseModel):
    x: float
    y: float
    z: float


class ClearanceMeasurement(BaseModel):
    """Minimum clearance measurement between two components."""
    target_component_id: int
    target_component_name: str
    target_cad_id: str

    neighbor_component_id: int
    neighbor_component_name: str
    neighbor_cad_id: str

    distance_mm: float
    point_on_target: Point3D
    point_on_neighbor: Point3D

    # C2: Directional clearance along best removal direction in addition to minimum distance
    directional_clearance_mm: Optional[float] = None
    removal_direction_vector: Optional[Tuple[float, float, float]] = None
    removal_direction_name: Optional[str] = None

    is_contact: bool = False
    is_pass: bool = True
    threshold_mm: float = 3.0
    clearance_type: str = "part_to_part"  # "part_to_part", "solid_interference", "mated_surface_contact", "bearing_radial_clearance", "slip_fit_clearance", "guard_clearance"
    classification: str = "CLEARANCE"  # "INTERFERENCE", "CONTACT", "CLEARANCE", "INDETERMINATE"
    intersection_volume_mm3: Optional[float] = None
    severity: str = "PASS"  # "PASS", "WARNING", "CRITICAL"
    notes: str = ""


# ─── Obstruction Schemas ──────────────────────────────────────────────────────

class ObstructingComponent(BaseModel):
    """Details of a component obstructing a target component along an access direction."""
    component_id: int
    component_name: str
    cad_entity_id: str
    distance_to_obstruction_mm: float
    blockage_ratio: float  # 0.0 (clear) to 1.0 (fully blocked)
    contact: bool = False
    severity: str = "WARNING"  # "INFO", "WARNING", "CRITICAL"
    nearest_point: Optional[Point3D] = None


class DirectionAccessResult(BaseModel):
    """Obstruction assessment along one specific approach/removal direction."""
    direction_name: str  # "+X", "-X", "+Y", "-Y", "+Z", "-Z"
    direction_vector: Tuple[float, float, float]
    is_clear: bool
    free_travel_mm: float
    blockage_ratio: float
    obstructing_components: List[ObstructingComponent] = Field(default_factory=list)


class ComponentObstructionReport(BaseModel):
    """Full obstruction analysis for a target component across all candidate directions."""
    target_component_id: int
    target_component_name: str
    target_cad_id: str

    best_direction: Optional[str] = None
    best_direction_vector: Optional[Tuple[float, float, float]] = None
    max_free_travel_mm: float = 0.0
    all_directions_blocked: bool = False
    freedom_cone_half_angle_deg: Optional[float] = None
    freedom_cone_extreme_rays: List[Tuple[float, float, float]] = Field(default_factory=list)
    freedom_sphere_samples: List[Dict[str, Any]] = Field(default_factory=list)

    directions: List[DirectionAccessResult] = Field(default_factory=list)
    feasible_candidate_directions: List[DirectionAccessResult] = Field(default_factory=list)
    confidence: str = "exact_brep"
    limitations: str = "Evaluated along 6 cardinal directions using OpenCASCADE analytical B-Rep curve-face intersector."


# ─── Disassembly Dependency Schemas ──────────────────────────────────────────

class DependencyNode(BaseModel):
    component_id: int
    name: str
    cad_entity_id: str
    component_type: str
    is_leaf: bool
    depth: int = 0


class DependencyEdge(BaseModel):
    precedent_id: int
    precedent_name: str
    dependent_id: int
    dependent_name: str
    reason: str  # "obstruction_along_+Z", "fastener_clamp", etc.


class DirectionAttempt(BaseModel):
    direction: str  # "+X", "-X", "+Y", "-Y", "+Z", "-Z", or vector string
    direction_vector: Optional[Tuple[float, float, float]] = None
    motion_type: str = "straight"  # "straight", "screw", "rotation", "piecewise_linear"
    freedom_cone_half_angle_deg: Optional[float] = None
    is_clear: bool
    max_travel_mm: Optional[float] = None
    colliding_components: List[str] = Field(default_factory=list)
    notes: str = ""


class DisassemblyStep(BaseModel):
    step_number: int
    component_id: int
    component_name: str
    cad_entity_id: str
    action: str  # "remove_fastener", "remove_component", "open_cover"
    removal_direction: Optional[str] = None
    direction_vector: Optional[Tuple[float, float, float]] = None
    motion_type: str = "straight"  # "straight", "screw", "rotation", "piecewise_linear"
    freedom_cone_half_angle_deg: Optional[float] = None
    rotation_axis: Optional[Tuple[float, float, float]] = None
    rotation_center: Optional[Tuple[float, float, float]] = None
    rotation_angle_deg: Optional[float] = None
    path_segments: List[Dict[str, Any]] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)  # Names of components that had to be removed before this step
    notes: str = ""
    member_component_ids: List[int] = Field(default_factory=list)
    is_unified_fastener: bool = False
    is_path_verified: bool = False
    path_validation_status: str = "unverified"  # "verified", "collision_detected", "cyclic", "unverified", "blocked"
    status_label: str = "Ready — path verified"  # "Ready — path verified", "Alternative direction found", "Prerequisite required", "No feasible straight-line path found", "Unresolved dependency cycle"
    colliding_components_along_path: List[str] = Field(default_factory=list)
    max_verified_travel_mm: Optional[float] = None
    tested_directions_count: int = 1
    feasible_directions: List[str] = Field(default_factory=list)
    direction_attempts: List[DirectionAttempt] = Field(default_factory=list)
    reorientation_required: bool = False
    step_effort_cost: float = 0.0


class DisassemblyGraph(BaseModel):
    assembly_id: int
    nodes: List[DependencyNode] = Field(default_factory=list)
    edges: List[DependencyEdge] = Field(default_factory=list)
    sequence: List[DisassemblyStep] = Field(default_factory=list)
    total_steps: int = 0
    estimated_fastener_count: int = 0
    sequence_status: str = "candidate"  # "candidate", "physically_verified", "partial_sequence", "cycle_detected", "candidate_with_path_collisions", "budget_exhausted"
    is_physically_verified: bool = False
    validation_notes: List[str] = Field(default_factory=list)
    verified_steps_count: int = 0
    unverified_steps_count: int = 0
    total_disassembly_effort_score: float = 0.0
    search_nodes_explored: int = 0
    is_search_budget_exhausted: bool = False
    unresolved_components: List[str] = Field(default_factory=list)
    unresolved_reasons: Dict[str, str] = Field(default_factory=dict)


# ─── Scoring Schemas ──────────────────────────────────────────────────────────

class ScoreDeduction(BaseModel):
    criterion: str  # "Access & Obstruction", "Clearance", "Disassembly Effort", "Fastener Complexity"
    penalty_points: float
    description: str
    measured_value: Optional[str] = None
    threshold: Optional[str] = None
    severity: str = "WARNING"  # "INFO", "WARNING", "CRITICAL"


class ComponentScore(BaseModel):
    component_id: int
    component_name: str
    cad_entity_id: str
    score: float  # 0 to 100
    rating: str   # "EXCELLENT" (90-100), "GOOD" (75-89), "FAIR" (50-74), "POOR" (<50)

    # Sub-scores
    access_score: float = 25.0
    clearance_score: float = 25.0
    disassembly_score: float = 25.0
    fastener_score: float = 25.0

    deductions: List[ScoreDeduction] = Field(default_factory=list)
    safety_warnings: List[str] = Field(default_factory=list)


# ─── Tool Approach Schemas ───────────────────────────────────────────────────

class ToolApproachResult(BaseModel):
    """Tool approach envelope assessment along fastener axis with tilt cone."""
    component_id: int
    component_name: str
    cad_entity_id: str
    tool_axis_vector: Tuple[float, float, float]
    tool_length_mm: float = 65.0
    tool_radius_mm: float = 8.0
    tilt_cone_half_angle_deg: float = 15.0
    is_tool_access_free: bool = True
    usable_tilt_angle_deg: float = 0.0
    blocking_components: List[str] = Field(default_factory=list)
    details: str = ""


class AssemblyServiceabilityReport(BaseModel):
    assembly_id: int
    filename: str
    overall_score: float
    overall_rating: str

    analyzed_components_count: int
    critical_issues_count: int
    warnings_count: int

    component_scores: List[ComponentScore] = Field(default_factory=list)
    tool_approaches: List[ToolApproachResult] = Field(default_factory=list)
    critical_safety_findings: List[str] = Field(default_factory=list)
    general_recommendations: List[str] = Field(default_factory=list)

    # Settings used
    settings: Dict[str, Any] = Field(default_factory=dict)
    is_cached: bool = False


class AnalysisJobStatus(BaseModel):
    job_id: str
    assembly_id: int
    status: str  # "pending", "processing", "completed", "failed"
    stage: str   # "initializing", "clearances", "obstructions", "graph", "scoring", "complete"
    percent: int
    elapsed_seconds: float
    is_cached: bool = False
    error: Optional[str] = None


# ─── Multi-Axis Sectioning Schemas (Phase D) ────────────────────────────────

class SectionPlaneRequest(BaseModel):
    point: List[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    normal: List[float] = Field(default_factory=lambda: [0.0, 0.0, 1.0])
    component_ids: Optional[List[int]] = None
    measure_clearance_between: Optional[List[int]] = None


class ComponentSectionOutline(BaseModel):
    component_id: int
    component_name: str
    area_mm2: float
    outlines: List[List[List[float]]] = Field(default_factory=list)


class SectionClearanceResult(BaseModel):
    component_a_id: int
    component_b_id: int
    component_a_name: str
    component_b_name: str
    clearance_mm: float
    point_a: List[float]
    point_b: List[float]


class AssemblySectionResponse(BaseModel):
    assembly_id: int
    plane_point: List[float]
    plane_normal: List[float]
    total_cut_area_mm2: float
    component_sections: List[ComponentSectionOutline] = Field(default_factory=list)
    clearance: Optional[SectionClearanceResult] = None

