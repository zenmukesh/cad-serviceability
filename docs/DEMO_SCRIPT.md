# 5-Minute Ideathon Judge Walkthrough Script

## Target Demo Sequence

### Minute 0:00 - 1:00: Problem & First Impression
1. **Launch:** Run `start_app.bat` (Windows) or `bash start_app.sh` (Linux/macOS).
2. **Dashboard:** Point out the loaded sample assembly (`gearbox_assembly.step`, 19 parts).
3. **Speed Highlight:** Point out the "Cached (Instant)" badge (< 100 ms retrieval) vs cold analytical calculation (~57s), highlighting the persistent cache architecture.

### Minute 1:00 - 2:00: Geometric Precision & 3D Navigation
1. **Navigation:** Demonstrate Fusion-style 3D controls (Orbit via Shift+Middle Click or ViewCube, Pan via Middle Click, Zoom via Scroll).
2. **Component Inspection:** Click on `FilterCanister` in the 3D canvas or component tree.
3. **Access & Freedom Sphere:** Switch to the **Access** tab and open the **Removal Directions** card.
   - Point out the 3D Freedom Sphere showing accessible extraction cones.
   - Highlight that +X is clear for 95 mm, while -X is obstructed by `BearingBlock_B` at exactly 2.00 mm.

### Minute 2:00 - 3:00: Cross-Sectioning & Clearance Verification
1. **Multi-Axis Sectioning:** Click the Section tool on the viewport bar.
2. **True-Shape Outlines:** Enable Top (Z) or Front (Y) cross-section to view true CAD boundary curves and hatching lines in real-time.
3. **Clearance Tab:** Navigate to the **Clearance** tab. Point out pairwise clearances measured with exact 3D contact points and severity ratings (PASS / WARNING / CRITICAL).

### Minute 3:00 - 4:00: Disassembly Planning & Physical Verification
1. **Sequence Tab:** Open the **Sequence** tab.
2. **Constraint DAG:** Show the step-by-step disassembly sequence with fastener grouping and physical swept-volume collision verification flags.
3. **Interactive Step Review:** Click step 1 (`FilterCanister` removal along +X) to show the animated extraction vector in 3D.

### Minute 4:00 - 5:00: Revision Comparison & Explainable Scoring
1. **Compare Tab:** Switch to the **Compare** tab.
2. **Diff View:** Select another assembly revision to view component count changes, volume deltas, and score differences in the structured diff table.
3. **Traceability:** Highlight that the 0-100 Serviceability Score is fully traceable to mechanical deductions (clearance deficit, access obstruction, fastener complexity, and sequence depth) rather than a black-box metric.
