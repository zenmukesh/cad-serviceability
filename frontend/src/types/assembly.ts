export interface BoundingBox {
  xmin: number
  xmax: number
  ymin: number
  ymax: number
  zmin: number
  zmax: number
  size_x: number
  size_y: number
  size_z: number
}

export interface Component {
  id: number
  assembly_id: number
  cad_entity_id: string
  name: string
  user_label: string | null
  parent_cad_id: string | null
  depth: number
  is_leaf: boolean
  component_type: string
  volume_mm3: number | null
  surface_area_mm2: number | null
  bounding_box: BoundingBox | null
  display_name: string
}

export interface Assembly {
  id: number
  filename: string
  sha256: string
  revision_label: string | null
  imported_at: string
  status: 'pending' | 'processing' | 'ready' | 'error'
  error_message: string | null
  importer_version: string | null
  component_count: number
  software_versions: Record<string, string> | null
}

export interface ComponentsResponse {
  assembly_id: number
  filename: string
  component_count: number
  components: Component[]
}

export interface MeshData {
  component_id: number
  vertices: number[]
  faces: number[]
  normals: number[]
  vertex_count: number
  face_count: number
}

export interface UploadResponse {
  assembly_id: number
  filename: string
  sha256: string
  status: string
  message: string
}
