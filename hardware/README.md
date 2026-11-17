# OKR Drum – Hardware

`okr_drum_blueprint.pdf` – A3 drawing at 1:5, dimensions in mm (print at 100 %, no
"fit to page"). Measure one real monitor before cutting: every base and strip position
follows from the monitors.

The drawing dates from the first plan: its parts list names a Pi Camera 3 Wide and 940 nm
LEDs. The rig as built uses the Pi HQ Camera and an 850 nm lamp from above (see below);
all wood and monitor dimensions are unchanged.

## Build summary
- **Screens:** 4 × LG Flatron W1946 (18.5", visible 41.0 × 23.0 cm, 1366 × 768 native; run
  at 1024 × 768 is fine), stands removed, mounted on 75 mm VESA with 1 cm spacers.
- **Layout:** pinwheel – each monitor's side bezel tucks against the next screen, giving a
  42.7 cm square arena with one ~1.6 cm bezel seam per corner (felt pads at contacts).
- **Wood:** base box 55.8 × 55.8 cm, 10 cm high; four 20 × 40 cm support strips (open sides
  for cooling), glued and screwed over the base sides, 2 steel L-brackets each.
- **Pedestal:** Ø 5 cm, 12.5 cm high (eye at mid-screen, 24.5 cm above the bench); matte grey.
- **Optional mirror top:** four 24.1 × 22.6 cm acrylic-mirror pieces in a pinwheel with a
  centre camera hole; optional floor mirror 42.5 × 42.5 cm with a matte grey disc (~20 cm).

## Electronics
- **Video:** one VGA output → powered 1-to-4 VGA splitter (250 MHz) → four equal-length VGA
  cables. Set every monitor to *Wide* (full width) and press *Auto adjust*.
- **Sync:** USB-TTL adapter (CH341T: jumpers on **TTL** and **3V3**) from the lab PC to the
  Pi: TXD → pin 10, RXD → pin 8, GND → pin 6. Leave VCC/SDA/SCL free.
  Pi 5: add `dtparam=uart0=on` to `/boot/firmware/config.txt`; the port is `/dev/ttyAMA0`.
- **Camera:** Pi HQ Camera + 4.2 mm CS IR lens, ~1 cm above the arena top. The HQ Camera
  has a built-in IR-cut filter – remove it for IR work. Focus with the IR light on.
- **IR light:** 850 nm CCTV lamp from above (open top), or 940 nm LED columns on the
  corner seams (mirror top). Tape over any built-in light sensor; switch the 12 V supply
  with a logic-level MOSFET module from the Pi or an Arduino.
