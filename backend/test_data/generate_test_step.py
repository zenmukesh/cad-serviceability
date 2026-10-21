"""
Synthetic STEP test assembly generator.

Creates a known-geometry test fixture:
  - Box 1: 100 × 50 × 30 mm at origin
  - Box 2: 40 × 40 × 40 mm, translated (120, 0, 0)
  - Cylinder: r=15mm h=60mm, translated (0, 80, 0)

This gives predictable bounding boxes, volumes, and surface areas
for use in unit tests without requiring an external STEP file.

Usage:
    python test_data/generate_test_step.py

Requires cadquery to be installed.
"""
from pathlib import Path
import sys

# Add backend to path when run as a script
sys.path.insert(0, str(Path(__file__).parent.parent))


def generate_test_step(output_path: Path = None) -> Path:
    """Generate the synthetic test assembly STEP file and return its path."""
    try:
        import cadquery as cq
    except ImportError:
        raise RuntimeError(
            "cadquery is required to generate test fixtures. "
            "Install it with: pip install cadquery"
        )

    if output_path is None:
        output_path = Path(__file__).parent / "simple_assembly.step"

    # Component 1: Base plate — 100×50×30 mm box at origin
    box1 = cq.Workplane("XY").box(100, 50, 30).translate((50, 25, 15))

    # Component 2: Bracket — 40×40×40 mm box offset in X
    box2 = cq.Workplane("XY").box(40, 40, 40).translate((140, 20, 20))

    # Component 3: Shaft — cylinder r=15 h=60 mm, offset in Y
    cyl = cq.Workplane("XY").cylinder(60, 15).translate((50, 95, 30))

    # Combine into a compound for single-shape STEP export
    # (true assembly hierarchy in STEP requires cadquery Assembly API)
    assembly = (
        cq.Assembly(name="TestAssembly")
        .add(box1, name="BasePlate", color=cq.Color("lightblue"))
        .add(box2, name="Bracket", color=cq.Color("gray"))
        .add(cyl, name="Shaft", color=cq.Color("steelblue"))
    )

    assembly.save(str(output_path))
    print(f"Test assembly written to: {output_path}")
    return output_path


# Known ground-truth values for tests
TEST_ASSEMBLY_EXPECTED = {
    "component_count_min": 1,   # At minimum 1 component extracted
    "total_volume_approx_mm3": (
        100 * 50 * 30          # box1
        + 40 * 40 * 40         # box2
        + 3.14159 * 15**2 * 60  # cylinder
    ),
    "bounding_box_xmax_min": 160.0,   # box2 extends to x=160
    "bounding_box_ymax_min": 115.0,   # cylinder extends to y ≈ 110
}


if __name__ == "__main__":
    generate_test_step()
