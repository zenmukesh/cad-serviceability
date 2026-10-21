/**
 * TypeScript definitions for CAD Serviceability Assessment.
 * Milestone 2: Clearances, Obstructions, Disassembly DAG, Explainable Scoring.
 */

export interface Point3D {
  x: number
  y: number
  z: number
}

export interface ClearanceMeasurement {
  target_component_id: number
  target_component_name: string
  target_cad_id: string

  neighbor_component_id: number
  neighbor_component_name: string
  neighbor_cad_id: string

  distance_mm: number
  point_on_target: Point3D
  point_on_neighbor: Point3D

  is_contact: boolean
  is_pass: boolean
  threshold_mm: number
  clearance_type: string
  classification?: 'INTERFERENCE' | 'CONTACT' | 'CLEARANCE' | 'INDETERMINATE'
  intersection_volume_mm3?: number
  severity: 'PASS' | 'WARNING' | 'CRITICAL'
  notes: string
}

export interface ObstructingComponent {
  component_id: number
  component_name: string
  cad_entity_id: string
  distance_to_obstruction_mm: number
  blockage_ratio: number
  contact: boolean
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
  nearest_point?: Point3D
}

export interface DirectionAccessResult {
  direction_name: string
  direction_vector: [number, number, number]
  is_clear: boolean
  free_travel_mm: number
  blockage_ratio: number
  obstructing_components: ObstructingComponent[]
}

export interface ComponentObstructionReport {
  target_component_id: number
  target_component_name: string
  target_cad_id: string
  best_direction?: string
  best_direction_vector?: [number, number, number]
  max_free_travel_mm: number
  all_directions_blocked: boolean
  directions: DirectionAccessResult[]
  confidence: string
  limitations: string
}

export interface DependencyNode {
  component_id: number
  name: string
  cad_entity_id: string
  component_type: string
  is_leaf: boolean
  depth: number
}

export interface DependencyEdge {
  precedent_id: number
  precedent_name: string
  dependent_id: number
  dependent_name: string
  reason: string
}

export interface DirectionAttempt {
  direction: string
  is_clear: boolean
  max_travel_mm?: number | null
  colliding_components: string[]
  notes: string
}

export interface DisassemblyStep {
  step_number: number
  component_id: number
  component_name: string
  cad_entity_id: string
  action: string
  removal_direction?: string
  prerequisites: string[]
  notes: string
  member_component_ids?: number[]
  is_unified_fastener?: boolean
  is_path_verified?: boolean
  path_validation_status?: 'verified' | 'collision_detected' | 'cyclic' | 'unverified' | 'blocked'
  status_label?: string
  colliding_components_along_path?: string[]
  max_verified_travel_mm?: number | null
  tested_directions_count?: number
  feasible_directions?: string[]
  direction_attempts?: DirectionAttempt[]
  reorientation_required?: boolean
  step_effort_cost?: number
}

export interface DisassemblyGraph {
  assembly_id: number
  nodes: DependencyNode[]
  edges: DependencyEdge[]
  sequence: DisassemblyStep[]
  total_steps: number
  estimated_fastener_count: number
  sequence_status?: 'candidate' | 'physically_verified' | 'partial_sequence' | 'cycle_detected' | 'candidate_with_path_collisions' | 'budget_exhausted'
  is_physically_verified?: boolean
  validation_notes?: string[]
  verified_steps_count?: number
  unverified_steps_count?: number
  total_disassembly_effort_score?: number
  search_nodes_explored?: number
  is_search_budget_exhausted?: boolean
  unresolved_components?: string[]
  unresolved_reasons?: Record<string, string>
}

export interface ScoreDeduction {
  criterion: string
  penalty_points: number
  description: string
  measured_value?: string
  threshold?: string
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
}

export interface ComponentScore {
  component_id: number
  component_name: string
  cad_entity_id: string
  score: number
  rating: 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR'

  access_score: number
  clearance_score: number
  disassembly_score: number
  fastener_score: number

  deductions: ScoreDeduction[]
  safety_warnings: string[]
}

export interface AssemblyServiceabilityReport {
  assembly_id: number
  filename: string
  overall_score: number
  overall_rating: 'EXCELLENT' | 'GOOD' | 'FAIR' | 'POOR'

  analyzed_components_count: number
  critical_issues_count: number
  warnings_count: number

  component_scores: ComponentScore[]
  critical_safety_findings: string[]
  general_recommendations: string[]
  settings: Record<string, any>
}
