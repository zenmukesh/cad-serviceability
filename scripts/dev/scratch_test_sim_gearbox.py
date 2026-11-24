"""
Development Simulation Script: Gearbox Assembly Motion
Benchmarking and prototyping script for the 19-part gearbox fixture.
"""
import sys
sys.path.insert(0, '.')
from app.database import get_db, init_db
from app.models.assembly import Assembly, Component
from app.services.geometry_service import build_disassembly_graph, get_assembly_shapes
import cadquery as cq

init_db()
db = next(get_db())
a = db.query(Assembly).filter(Assembly.filename.like('%gearbox%')).first()
shapes = get_assembly_shapes(a.id, db)
leaf_components = db.query(Component).filter(Component.assembly_id == a.id, Component.is_leaf == 1).all()
comp_by_id = {c.id: c for c in leaf_components}

graph = build_disassembly_graph(a.id, db)
print(f"Total sequence steps for gearbox: {len(graph.sequence)}")

asm_xmin = min(c.bb_xmin for c in leaf_components)
asm_xmax = max(c.bb_xmax for c in leaf_components)
asm_ymin = min(c.bb_ymin for c in leaf_components)
asm_ymax = max(c.bb_ymax for c in leaf_components)
asm_zmin = min(c.bb_zmin for c in leaf_components)
asm_zmax = max(c.bb_zmax for c in leaf_components)

DIR_VECTORS = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}

installed_ids = {c.id for c in leaf_components}

for s in graph.sequence:
    moving_ids = s.member_component_ids if s.member_component_ids else [s.component_id]
    moving_comps = [comp_by_id[cid] for cid in moving_ids if cid in comp_by_id]
    r_dir = s.removal_direction or "+Z"
    vec = DIR_VECTORS.get(r_dir, (0.0, 0.0, 1.0))
    vx, vy, vz = vec

    obs_ids = installed_ids - set(moving_ids)

    m_xmin = min(c.bb_xmin for c in moving_comps)
    m_xmax = max(c.bb_xmax for c in moving_comps)
    m_ymin = min(c.bb_ymin for c in moving_comps)
    m_ymax = max(c.bb_ymax for c in moving_comps)
    m_zmin = min(c.bb_zmin for c in moving_comps)
    m_zmax = max(c.bb_zmax for c in moving_comps)

    if vx > 0:
        L_exit = max(20.0, (asm_xmax - m_xmin) + 10.0)
    elif vx < 0:
        L_exit = max(20.0, (m_xmax - asm_xmin) + 10.0)
    elif vy > 0:
        L_exit = max(20.0, (asm_ymax - m_ymin) + 10.0)
    elif vy < 0:
        L_exit = max(20.0, (m_ymax - asm_ymin) + 10.0)
    elif vz > 0:
        L_exit = max(20.0, (asm_zmax - m_zmin) + 10.0)
    else:
        L_exit = max(20.0, (m_zmax - asm_zmin) + 10.0)
    L_exit = min(L_exit, 400.0)

    swept_xmin = min(m_xmin, m_xmin + L_exit * vx)
    swept_xmax = max(m_xmax, m_xmax + L_exit * vx)
    swept_ymin = min(m_ymin, m_ymin + L_exit * vy)
    swept_ymax = max(m_ymax, m_ymax + L_exit * vy)
    swept_zmin = min(m_zmin, m_zmin + L_exit * vz)
    swept_zmax = max(m_zmax, m_zmax + L_exit * vz)

    candidate_obs = []
    for oid in obs_ids:
        oc = comp_by_id[oid]
        if (swept_xmax >= oc.bb_xmin and swept_xmin <= oc.bb_xmax and
            swept_ymax >= oc.bb_ymin and swept_ymin <= oc.bb_ymax and
            swept_zmax >= oc.bb_zmin and swept_zmin <= oc.bb_zmax):
            candidate_obs.append(oc)

    step_size = max(4.0, min(15.0, (m_xmax - m_xmin + m_ymax - m_ymin + m_zmax - m_zmin) / 6))
    t_vals = []
    curr_t = step_size
    while curr_t <= L_exit:
        t_vals.append(curr_t)
        curr_t += step_size

    collision_found = False
    colliding_obs_name = None
    collision_dist = 0.0
    collision_vol = 0.0

    for mc in moving_comps:
        m_shape = shapes.get(mc.cad_entity_id)
        if not m_shape:
            continue
        for t in t_vals:
            shifted = m_shape.translate(cq.Vector(t * vx, t * vy, t * vz))
            for oc in candidate_obs:
                o_shape = shapes.get(oc.cad_entity_id)
                if not o_shape:
                    continue
                try:
                    common = shifted.intersect(o_shape)
                    if common and not common.isNull():
                        vol = float(common.Volume())
                        if vol > 1e-3:
                            collision_found = True
                            colliding_obs_name = oc.display_name
                            collision_dist = t
                            collision_vol = vol
                            break
                except Exception:
                    pass
            if collision_found:
                break
        if collision_found:
            break

    status_str = f"BLOCKED by {colliding_obs_name} at d={collision_dist:.1f}mm (vol={collision_vol:.1f}mm3)" if collision_found else f"VERIFIED CLEAR (d={L_exit:.1f}mm)"
    print(f"Step {s.step_number:2d}: {s.component_name:30} Dir={r_dir:2} -> {status_str}")

    installed_ids.difference_update(moving_ids)
