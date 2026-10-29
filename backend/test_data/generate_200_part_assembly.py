"""
Generate synthetic 200-part test fixture for performance benchmarking.
Structure:
- 1 BasePlate: 600 x 500 x 25 mm
- 99 Blocks: 25 x 25 x 20 mm arranged in a 9 x 11 grid mounted on the base plate
- 100 Fasteners/Bolts: cylindrical bolts (r=4 mm, head r=7 mm) arranged in a 10 x 10 grid
Total components = 1 + 99 + 100 = 200 components.
"""
from pathlib import Path
import cadquery as cq

def generate_200_part_assembly(output_path: Path = None) -> Path:
    if output_path is None:
        output_path = Path(__file__).parent / "grid_200_assembly.step"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Generating 200-part assembly at {output_path}...")

    # 1. Base Plate
    base_plate = cq.Workplane("XY").box(600, 500, 25).translate((300, 250, 12.5))
    asm = cq.Assembly(name="Grid200Assembly")
    asm.add(base_plate, name="BasePlate", color=cq.Color("lightgray"))

    # 2. 99 Blocks (9 rows x 11 cols = 99 blocks)
    block_shape = cq.Workplane("XY").box(25, 25, 20).translate((12.5, 12.5, 10))
    block_count = 0
    for r in range(9):
        for c in range(11):
            x = 40.0 + c * 50.0
            y = 40.0 + r * 50.0
            z = 25.0
            b_placed = block_shape.translate((x, y, z))
            block_count += 1
            asm.add(b_placed, name=f"Block_{block_count:03d}", color=cq.Color("teal"))

    # 3. 100 Bolts (10 rows x 10 cols = 100 bolts)
    # Fastener cylinder shaft r=4, h=25, head r=7, h=6
    bolt_shaft = cq.Workplane("XY").cylinder(25, 4).translate((0, 0, 12.5))
    bolt_head = cq.Workplane("XY").cylinder(6, 7).translate((0, 0, 25 + 3))
    bolt_solid = bolt_shaft.union(bolt_head)

    bolt_count = 0
    for r in range(10):
        for c in range(10):
            x = 65.0 + c * 50.0
            y = 35.0 + r * 45.0
            z = 0.0 # seated into the plate
            b_placed = bolt_solid.translate((x, y, z))
            bolt_count += 1
            asm.add(b_placed, name=f"BaseBolt_{bolt_count:03d}", color=cq.Color("gold"))

    total = 1 + block_count + bolt_count
    assert total == 200, f"Expected 200 parts, got {total}"

    asm.save(str(output_path))
    print(f"Successfully generated {total}-part assembly: {output_path}")
    return output_path

if __name__ == "__main__":
    generate_200_part_assembly()
