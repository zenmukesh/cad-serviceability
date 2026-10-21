import cadquery as cq
import time

# Create a small assembly:
# 1. Base plate
# 2. Bracket
# 3. Pin trapped between them or sliding out

base = cq.Workplane().box(100, 100, 10).val() # Z: -5 to 5
# Wall at X = 30 to 40, Z = 5 to 35
wall = cq.Workplane().transformed(offset=(35, 0, 20)).box(10, 80, 30).val()
# Moving block at X = 0, Z = 15 (size 20x20x20)
block = cq.Workplane().transformed(offset=(0, 0, 15)).box(20, 20, 20).val()

# Moving block along +X: it should collide with the wall around X = 20-30!
# Moving block along +Z: it is completely unobstructed!

def check_motion(shape, direction, max_dist, obstacles, step_size=5.0):
    vx, vy, vz = direction
    t = step_size
    while t <= max_dist:
        shifted = shape.translate(cq.Vector(t * vx, t * vy, t * vz))
        for obs_name, obs_shape in obstacles.items():
            common = shifted.intersect(obs_shape)
            if common and not common.isNull():
                vol = float(common.Volume())
                if vol > 1e-3:
                    return False, obs_name, t, vol
        t += step_size
    return True, None, max_dist, 0.0

obstacles = {"wall": wall, "base": base}

t0 = time.time()
res_x, obs_x, dist_x, vol_x = check_motion(block, (1, 0, 0), 100.0, obstacles)
print(f"Motion +X: clear={res_x}, obs={obs_x}, dist={dist_x}, vol={vol_x:.2f} (elapsed: {time.time()-t0:.3f}s)")

t0 = time.time()
res_z, obs_z, dist_z, vol_z = check_motion(block, (0, 0, 1), 100.0, obstacles)
print(f"Motion +Z: clear={res_z}, obs={obs_z}, dist={dist_z}, vol={vol_z:.2f} (elapsed: {time.time()-t0:.3f}s)")
