// OKR Drum - mouse pedestal (3D-printable, one piece, no supports)
// All sizes in mm. Change the numbers below, then F6 (render) and File > Export > STL.
//
// The mouse sits on a 50 mm platform 125 mm above the drum floor (the 10 cm base top), which
// puts its eyes at mid-screen. The platform overhangs a thin stem, which keeps mice from
// climbing down. The top edge is left sharp: the camera calibration clicks this rim and
// expects a 50 mm diameter (change it in the calibration tool if you change platform_d).

/* [Main sizes] */
total_height  = 125;   // drum floor to platform top
platform_d    = 50;    // platform diameter (calibration uses this)
platform_t    = 6;     // straight edge of the platform disc
stem_d        = 24;    // stem diameter
flare         = 13;    // height of the 45-degree cone under the platform (prints without support)

/* [Foot] */
foot_d        = 110;   // foot diameter
foot_t        = 5;     // foot thickness
foot_fillet   = 14;    // cone from foot into stem (stiffness)
screw_holes   = 3;     // 0 = none
screw_d       = 4.2;   // wood screw / M4
screw_head_d  = 8.5;   // countersink
screw_circle  = 84;    // hole circle diameter
magnet_pockets= 0;     // pockets underneath for glued-in disc magnets (e.g. on a steel plate)
magnet_d      = 10.4;
magnet_h      = 3.2;

/* [Top surface] */
grip_rings    = true;  // shallow concentric grooves for grip
ring_pitch    = 2.0;
ring_depth    = 0.4;
centre_mark   = true;  // small cross at the centre (checks the calibration centre)

$fn = 128;

// ------------------------------------------------------------------
module top_surface_cut() {
    if (grip_rings)
        for (r = [ring_pitch * 2 : ring_pitch : platform_d/2 - 3])
            translate([0, 0, total_height - ring_depth])
                difference() {
                    cylinder(d = 2*r + 0.8, h = ring_depth + 1);
                    translate([0, 0, -0.5]) cylinder(d = 2*r - 0.8, h = ring_depth + 2);
                }
    if (centre_mark)
        translate([0, 0, total_height - 0.6])
            for (a = [0, 90]) rotate(a) translate([-4, -0.5, 0]) cube([8, 1, 1]);
}

module column() {
    // stem
    translate([0, 0, foot_t - 0.01]) cylinder(d = stem_d, h = total_height - foot_t - platform_t - flare + 0.02);
    // 45-degree flare to the platform
    translate([0, 0, total_height - platform_t - flare])
        cylinder(d1 = stem_d, d2 = platform_d, h = flare + 0.01);
    // platform disc (sharp top edge)
    translate([0, 0, total_height - platform_t]) cylinder(d = platform_d, h = platform_t);
}

module foot() {
    difference() {
        union() {
            cylinder(d = foot_d, h = foot_t);
            translate([0, 0, foot_t - 0.01]) cylinder(d1 = stem_d + 2*foot_fillet, d2 = stem_d, h = foot_fillet);
        }
        if (screw_holes > 0)
            for (i = [0 : screw_holes - 1]) rotate(i * 360 / screw_holes + 90)
                translate([screw_circle/2, 0, 0]) {
                    translate([0, 0, -1]) cylinder(d = screw_d, h = foot_t + 2);
                    translate([0, 0, foot_t - (screw_head_d - screw_d)/2])
                        cylinder(d1 = screw_d, d2 = screw_head_d, h = (screw_head_d - screw_d)/2 + 0.01);
                }
        if (magnet_pockets > 0)
            for (i = [0 : magnet_pockets - 1]) rotate(i * 360 / magnet_pockets + 30)
                translate([screw_circle/2 - 10, 0, -0.01]) cylinder(d = magnet_d, h = magnet_h);
    }
}

module pedestal() {
    difference() {
        union() { foot(); column(); }
        top_surface_cut();
    }
}

// ------------------------------------------------------------------
pedestal();
