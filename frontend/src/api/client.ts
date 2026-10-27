import axios from 'axios'
import type { Assembly, ComponentsResponse, MeshData, UploadResponse } from '../types/assembly'
import type {
  AssemblyServiceabilityReport,
  ClearanceMeasurement,
  ComponentObstructionReport,
  DisassemblyGraph,
  AssemblySectionResponse,
} from '../types/serviceability'

const client = axios.create({
  baseURL: '',
  headers: { 'Content-Type': 'application/json' }
})

export async function uploadStep(
  file: File,
  revisionLabel?: string
): Promise<UploadResponse> {
  const form = new FormData()
  form.append('file', file)
  if (revisionLabel) form.append('revision_label', revisionLabel)
  const res = await client.post<UploadResponse>('/api/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
  return res.data
}

export async function listAssemblies(): Promise<Assembly[]> {
  const res = await client.get<Assembly[]>('/api/assemblies')
  return res.data
}

export async function getAssembly(id: number): Promise<Assembly> {
  const res = await client.get<Assembly>(`/api/assemblies/${id}`)
  return res.data
}

export async function getAssemblyComponents(id: number): Promise<ComponentsResponse> {
  const res = await client.get<ComponentsResponse>(`/api/assemblies/${id}/components`)
  return res.data
}

export async function getComponentMesh(componentId: number): Promise<MeshData> {
  const res = await client.get<MeshData>(`/api/geometry/${componentId}`)
  return res.data
}

export async function updateComponentLabel(
  componentId: number,
  label: string
): Promise<void> {
  await client.patch(`/api/components/${componentId}/label`, { user_label: label })
}

export async function pollAssemblyStatus(
  id: number,
  onStatus: (assembly: Assembly) => void,
  maxWait = 120000
): Promise<Assembly> {
  const interval = 2000
  const start = Date.now()

  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const assembly = await getAssembly(id)
        onStatus(assembly)
        if (assembly.status === 'ready' || assembly.status === 'error') {
          resolve(assembly)
          return
        }
        if (Date.now() - start >= maxWait) {
          reject(new Error('Assembly processing timed out'))
          return
        }
        setTimeout(poll, interval)
      } catch (err) {
        reject(err)
      }
    }
    poll()
  })
}

export async function getServiceabilityReport(
  assemblyId: number,
  minClearanceMm = 3.0
): Promise<AssemblyServiceabilityReport> {
  const res = await client.get<AssemblyServiceabilityReport>(
    `/api/assemblies/${assemblyId}/serviceability`,
    { params: { min_clearance_mm: minClearanceMm } }
  )
  return res.data
}

export async function runServiceabilityAnalysis(
  assemblyId: number,
  minClearanceMm = 3.0
): Promise<AssemblyServiceabilityReport> {
  const res = await client.post<AssemblyServiceabilityReport>(
    `/api/assemblies/${assemblyId}/analyze`,
    { min_clearance_mm: minClearanceMm }
  )
  return res.data
}

export async function getComponentObstructions(
  assemblyId: number,
  componentId: number
): Promise<ComponentObstructionReport> {
  const res = await client.get<ComponentObstructionReport>(
    `/api/assemblies/${assemblyId}/components/${componentId}/obstructions`
  )
  return res.data
}

export async function getComponentClearances(
  assemblyId: number,
  componentId: number,
  minClearanceMm = 3.0
): Promise<ClearanceMeasurement[]> {
  const res = await client.get<ClearanceMeasurement[]>(
    `/api/assemblies/${assemblyId}/components/${componentId}/clearances`,
    { params: { min_clearance_mm: minClearanceMm } }
  )
  return res.data
}

export async function getAllClearances(
  assemblyId: number,
  minClearanceMm = 3.0
): Promise<ClearanceMeasurement[]> {
  const res = await client.get<ClearanceMeasurement[]>(
    `/api/assemblies/${assemblyId}/clearances`,
    { params: { min_clearance_mm: minClearanceMm } }
  )
  return res.data
}

export async function getDependencyGraph(assemblyId: number): Promise<DisassemblyGraph> {
  const res = await client.get<DisassemblyGraph>(`/api/assemblies/${assemblyId}/dependency-graph`)
  return res.data
}

export async function getAssemblySection(
  assemblyId: number,
  params: {
    point: [number, number, number]
    normal: [number, number, number]
    component_ids?: number[]
    measure_clearance_between?: [number, number]
  }
): Promise<AssemblySectionResponse> {
  const res = await client.post<AssemblySectionResponse>(
    `/api/assemblies/${assemblyId}/section`,
    params
  )
  return res.data
}

export default client
