#!/usr/bin/env python
# Copyright 2015, Jason S. McMullan <jason.mcmullan@gmail.com>
#
# stl2brundlefab.py: Convert STL objects into GCode for BrundleFab
#
# Licensed under the MIT License:
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
############################ Theory of Operation ###########################
#
# This program takes as input a STL 3D object file, and emits GCode
# suitable for input to the BrundleFab thermal fusing powderbed printer.
#
# The BrundleFab has a Y axis carriage with a combined ink head, thermal
# fuser, and repowder blade, herein called the 'layer head'.
#
# The layer head completely covers the feed bin, and can be used to preserve
# powder quality between prints.
#           ___
#          /   T
#       __/_ F _\__________oH
#    ||/ <-R          S-> \ H                                      ||
#    ||-------------------||-------------------||                  ||
#    ||    Feed Bin       ||    Part Bin       ||    Waste Bin     ||
#    ||                   ||===================||                  ||
#    ||===================||         ::        ||                  ||
#    ||       E :: Axis   ||       Z :: Axis   ||                  ||
#
#  Key:
#
#    || - Wall of the powder chambers
#    -- - Top of the feed/part powder layers
#    == - Top of the feed/part pistons
#    F  - Thermal fuser (halogen bulb)
#    T  - Thermal sensor
#    R  - Recoating blade
#    S  - Powder sealing blade
#    H  - Ink head
#    o  - Ink head rail
#
# A BrundleFab layer is constructed as follows:
#
# 1. The layer head begins at the minimum X position, positioning
#    the repowder blade at the start of the Feed Bin
# 2. The Feed Bin raises by one layer width
# 3. The layer head advances in X, until the repowder blade (R) is at the
#    start of the Waste Bin, depositing powder as it advances.
# 4. The Part Bin (Z) drops by 2mm, and the Feed Bin (E)
#    drops by 2mm.
#    This is needed so that the repowder blade will not disturb the existing
#    powder layer during the inking pass.
# 5. The layer head retracts in X until the ink head (H) is at the end
#    of the Part Bin.
# 6.The ink deposition phase then begins, depositing ink on the
#    fresh powder layer, as the layer head retracts in X.
# 7. The layer head retacts in X until the the fuser (F) is at the start
#    at the start of Part Bin.
# 8. The fuser is enabled, and slowly advances in X during warm up
# 9. The layer head advances in X until the the fuser (F) is at the
#    start of the Waste Bin
# 10. The fuser is disabled.
# 11.The layer head is fully retracted.
#    This will position the repowder blade (R) at the start of the powder
#    feed bin.
# 12.The Feed Bin raises by 2mm
#
# Repeat steps 1 - 12 for all layers.

import re
import sys
import cairo
import numpy
import getopt
import tempfile
import subprocess
from xml.dom import minidom

X_BIN_FEED=0        # Start of the feed bin
X_BIN_PART=198      # Start of the part bin
X_BIN_WASTE=385     # Start of the waste bin

X_OFFSET_RECOAT=0   # Offset of the recoater blade
X_OFFSET_FUSER=60   # Offset of midpoint of fuser
X_OFFSET_PEN=195    # Offset of the pen

FEED_RETRACT=2.0    # E retraction, in mm
FEED_SPREAD=3000    # Spread rate while depositing the layer
FEED_POWDER=4500    # Extruder feed rate (mm/minute)
FEED_FUSER_WARM=200 # Fuser pass rate during warm-up (mm/minute)
TIME_FUSER_WARM=6   # Time (in seconds) for fuser to complete its warm-up
FEED_FUSER_HOT=300  # Fuser pass rate during hot (mm/minute)
FEED_PEN=5000       # Pen movement (mm/minute)
X_DPI=96.0
Y_DPI=96.0

Y_DOTS=12

config = {}

def gc(comment, code = None):
    if not config['do_gcode']:
        return

    if config['gcode_terse']:
        comment = None

    if comment == None and code != None:
        print "%s" % (code)
    elif code != None:
        print "%s ; %s" % (code, comment)
    elif comment != None:
        print "; %s" % (comment)
    pass

def brundle_prep(name, max_z_mm, layers):
    gc("Print %s to the BrundleFab, %dmm, %d layers" % (name, max_z_mm, layers))
    gc("Units are mm", "G21")
    gc("Absolute positioning", "G90")
    gc("Set pen base offset", "G10 L1 P0 X%.3f" % (X_OFFSET_PEN))
    gc("Set black tool offset", "G10 L1 P1 X%.3f" % (X_OFFSET_PEN))
    gc("Set fuser tool offset", "G10 L1 P20 X%.3f" % (X_OFFSET_FUSER))
    gc("Set repowder blade offset", "G10 L1 P21 X%.3f" % (X_OFFSET_RECOAT))
    gc("Set thermal monitor tool offset", "G10 L1 P22 X%.3f" % (X_OFFSET_THERM))
    gc("Ink spray rate (sprays/dot)", "T1 S%d" % (config['sprays']))
    gc("Re-home the ink head", "G28 Y0")

    if config['do_startup']:
        gc(None, "M117 Ready to home")
        gc("Let the user make sure we're ready to home axes", "M0")
        gc("Home print axes", "G28 X0 Y0 E0")
        gc("NOTE: Z is _not_ homed, as it may be part of a multi-file print")

        gc(None, "M117 Prep Part")
        gc("Select the recoater tool", "T21")
        gc("Wait for Z prep", "M0")
        gc("Move to start of the Waste Bin", "G0 X%.3f" % (X_BIN_WASTE))

        gc(None, "M117 Levelling")
        gc("Move to start of the Part Bin", "G1 X%.3f F%.3f" % (X_BIN_PART, FEED_SPREAD))
        gc(None, "M117 Feed %dmm" % (int(max_z_mm)+5))
        gc("Wait for manual fill operation", "M0")
        gc("Clear status message", "M117")

    gc("Select repowder tool", "T21")
    gc("Move to feed start", "G1 X%.3f" % (X_BIN_FEED))

def in2mm(inch):
    return inch * 25.4

def mm2in(mm):
    return mm / 25.4

def brundle_line(x_dots, w_dots, toolmask, weave=True):
    origin = None
    for i in range(0, w_dots):
        if toolmask[i] != 0:
            origin = i
            break
    if origin == None:
        return

    gc(None, "T0")
    gc(None, "T1 P0")
    gc(None, "G1 X%.3f F%.3f" % (X_BIN_PART + in2mm(x_dots / X_DPI), FEED_PEN))
    gc(None, "G1 Y%.3f" % (in2mm(origin / Y_DPI)))

    for i in range(origin+1, w_dots):
        if (toolmask[origin] != toolmask[i]) or (i == w_dots - 1):
            if (i == w_dots - 1) and (toolmask[origin] == 0):
                break
            gc(None, "T1 P%d" % (toolmask[origin]))
            gc(None, "G1 Y%.3f" % (in2mm((i - 1) / Y_DPI)))
            origin = i

    # Switching to tool 0 will cause a forward flush of the
    # inkbar, and the ink head will end up at the end of the
    # line.
    gc(None, "T0")

    # For interweave support, we retract X by a half-dot, and
    # cover the dots inbetween the forward pass on the
    # reverse pass
    if weave:
        gc(None, "G1 X%.3f F%.3f" % (X_BIN_PART + in2mm((x_dots - 0.5) / X_DPI), FEED_PEN))

    # Switch back to T1 to ink on the reverse movement of
    # then inkbar
    gc(None, "T1 P0")
    gc(None, "G0 Y0")


# Note: h_dots _must_ be a multiple of Y_DOTS!
def brundle_layer(w_dots, h_dots, surface, weave=True):
    if not config['do_layer']:
        return

    stride = surface.get_stride()
    image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
    image = numpy.reshape(image, (stride, h_dots))
    image = numpy.greater(image, 0)

    y = 0
    dotlines = numpy.vsplit(image, h_dots/Y_DOTS)
    for dotline in dotlines:
        toolmask = numpy.zeros((stride))
        for l in range(0, Y_DOTS):
            toolmask = toolmask + dotline[l]*(1 << l)
        brundle_line(y, w_dots, toolmask, weave)
        y = y + Y_DOTS

def brundle_layer_prep(e_delta_mm):
    gc("1. Assume layer head is at feed start")
    gc(  "Select recoat tool", "T21")

    if config['do_extrude']:
        gc("2. Raise Feed Bin by one layer width")
        gc(  "Relative positioning", "G91")
        gc(  "Extrude a feed layer", "G1 E%.3f F%d" % (e_delta_mm, FEED_POWDER))
        gc(  "Absolute positioning", "G90")

        gc("3. Advance recoat blade past Waste Bin")
        gc(  "Advance to waste bin", "G1 X%.3f F%d" % (X_BIN_WASTE+15, FEED_SPREAD))
        gc("4. Drop Part Bin by %.3fmm, and Feed Bin by %.3fmm" % (FEED_RETRACT, FEED_RETRACT))
        gc(  "Relative positioning", "G91")
        gc(  "Drop bins to get out of the way", "G1 E%.3f Z%.3f F%d" % (-FEED_RETRACT, FEED_RETRACT, FEED_POWDER))
        gc(  "Absolute positioning", "G90")

    if config['do_layer']:
        gc("5. Move pen to start of the part bin")
        gc(  "Select ink tool", "T1 P0")
        gc(  "Move pen to end of the part bin", "G0 X%.3f" % (X_BIN_PART))
        gc("6. Ink the layer")
        # See brundle_layer()

def brundle_layer_finish(z_delta_mm):
    if config['do_fuser']:
        gc("7. Select fuser, and advance to Waste Bin start")
        gc(  "Select fuser, but unlit", "T20 P0 Q0")
        x_warm_delta_mm = FEED_FUSER_WARM * TIME_FUSER_WARM / 60
        gc(  "Advance to Waste Bin start + warm up", "G0 X%.3f" % (X_BIN_WASTE + x_warm_delta_mm+50))
        gc("8. The fuser is enabled, and brought up to temp")
        gc(  "Select fuser and temp", "T20 P%.3f Q%.3f" % (config['fuser_temp']+5, config['fuser_temp']-5))

        gc("9. Retract fuser to start of Part Bin")
        gc(  "Fuser warm-up", "G1 X%.3f F%d" % (X_BIN_WASTE+50, FEED_FUSER_WARM))
        for delta in range(0, int(X_BIN_WASTE - X_BIN_PART)/10):
            gc(  "Fuse ..", "G1 X%.3f F%d" % (X_BIN_WASTE - delta*10, FEED_FUSER_HOT))
        gc(  "Fuse ..", "G1 X%.3f F%d" % (X_BIN_PART, FEED_FUSER_HOT))
        gc("10. The fuser is disabled", "T20 P0 Q0")

    gc("11. Retract recoating blade to start of the Feed Bin")
    gc(  "Select the recoating tool", "T21")
    gc(  "Move to start", "G0 X%.3f Y0" % (X_BIN_FEED))

    if config['do_extrude']:
        gc("12. The Feed Bin and Part bin raises by %.3fmm" % FEED_RETRACT)
        gc(  "Relative positioning", "G91")
        gc(  "Raise the bins", "G1 E%.3f Z%.3f F%d" % (FEED_RETRACT, z_delta_mm - FEED_RETRACT, FEED_POWDER))
        gc(  "Absolute positioning", "G90")

def draw_path(cr, poly):
    x_shift = config['x_shift_mm']
    y_shift = config['y_shift_mm']
    p = poly.getAttribute("points")
    p = re.sub(r'\s+',r' ', p)
    p = re.sub(r' *, *',r' ', p)
    pairs = zip(*[iter(p.split(' '))]*2)

    moved = False
    for pair in pairs:
        point=[float(f) for f in pair]
        if moved:
            cr.line_to(point[0] + x_shift, point[1] + y_shift)
        else:
            cr.move_to(point[0] + x_shift, point[1] + y_shift)
            moved = True
    cr.close_path()

def group_z(layer):
    z_mm = None
    if layer.hasAttribute("slic3r:z"):
        # slic3r
        z_mm = float(layer.getAttribute("slic3r:z")) * 1000000
    else:
        # repsnapper
        label = layer.getAttribute("id").split(':')
        if len(label) != 2:
            return
        z_mm = float(label[1])
    return z_mm

def group_to_slice(layer, n, this_layer_mm = None, next_layer_mm = None):
    # Create a new cairo surface
    w_dots = int(mm2in(config['y_bound_mm']) * Y_DPI)
    h_dots = int(mm2in(config['x_bound_mm']) * X_DPI)

    if (h_dots % Y_DOTS) != 0:
        h_dots = int((h_dots + Y_DOTS - 1) / Y_DOTS) * Y_DOTS

    surface = cairo.ImageSurface(cairo.FORMAT_A8, w_dots, h_dots)
    cr = cairo.Context(surface)
    cr.set_antialias(cairo.ANTIALIAS_NONE)

    i = 0
    contours = []
    holes = []
    for poly in layer.getElementsByTagName("polygon"):
        if poly.hasAttribute("slic3r:type"):
            # slic3r
            mode = poly.getAttribute("slic3r:type")
            if mode == 'contour':
                contours.append(poly)
            elif mode == 'hole':
                holes.append(poly)
        elif poly.hasAttribute("fill"):
            fill = poly.getAttribute("fill")
            if fill == 'black':
                contours.append(poly)
            elif fill == 'white':
                holes.append(poly)

    # Scale from mm to dots
    cr.scale(mm2in(1.0) * X_DPI, mm2in(1.0) * Y_DPI)

    # Draw filled area
    for contour in contours:
        draw_path(cr, contour)
        cr.fill()

    # Draw holes
    cr.set_operator(cairo.OPERATOR_CLEAR)
    for hole in holes:
        draw_path(cr, hole)
        cr.fill()

    # Emit the image
    surface.flush()
    if config['do_png']:
        surface.write_to_png("layer-%03d.png" % n)

    brundle_layer_prep(this_layer_mm)
    brundle_layer(w_dots, h_dots, surface, weave=config['do_weave'])
    brundle_layer_finish(next_layer_mm)

def usage():
    print """
svg2brundlefab [options] sourcefile.stl >sourcefile.gcode
svg2brundlefab [options] --svg sourcefile.svg >sourcefile.gcode

  -h, --help            This help

Input conversion:
  --svg                 Treat input as a SVG file
  -s, --slicer=SLICER   Select a slicer ('repsnapper' or 'slic3r')

Transformation:
  --units=in            Assume model was in inches
  --units=mm            Assume model was in mm (default)
  --scale N             Scale object (before offsetting)
  --x-offset N          Add a X offset (in mm) to the layers
  --y-offset N          Add a Y offset (in mm) to the layers

Fuser control:
  --fuser-temp N        Temperature of the fuser (at heat shield), in C.

GCode output:
  -G, --no-gcode        Do not generate any GCode (assumes S, E, and L)
  -S, --no-startup      Do not generate GCode startup code
  -L, --no-layer        Do not generate layer inking commands
  -W, --no-weave        Do not generate interweave commands
  -F, --no-fuser        Do not generate fuser commands
  -E, --no-extrude      Do not generate E or Z axis commands
  -p, --png             Generate 'layer-XXX.png' files, one for each layer

"""

def main():
    config['gcode_terse'] = False
    config['fuser_temp'] = 0.0      # Celsius
    config['sprays'] = 1            # Sprays per pixel
    config['x_bound_mm'] = 200.0
    config['y_bound_mm'] = 200.0
    config['x_shift_mm'] = 0.0
    config['y_shift_mm'] = 0.0
    config['z_slice_mm'] = 0.5
    config['scale'] = 1.0
    config['do_png'] = False
    config['do_gcode'] = True
    config['do_startup'] = True
    config['do_layer'] = True
    config['do_fuser'] = True
    config['do_extrude'] = True
    config['do_weave'] = True
    config['slicer'] = 'slic3r'

    unit = {}
    unit['mm'] = 1.0
    unit['in'] = 25.4
    unit['ti'] = 2.54   # Tenths of inches

    units = 'mm'

    try:
        opts, args = getopt.getopt(sys.argv[1:], "EFGhLo:ps:SW", [
                "help",
                "no-gcode","no-startup","no-extrude","no-fuser","no-layer",
                "png",
                "slicer=","svg","units=",
                "x-offset=","y-offset=","z-slice=","scale=",
                "no-weave","overspray=",
                "fuser-temp="])
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)

    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-S","--no-startup"):
            config['do_startup'] = False
        elif o in ("-E","--no-extrude"):
            config['do_extrude'] = False
        elif o in ("-F","--no-fuser"):
            config['do_fuser'] = False
        elif o in ("-L","--no-layer"):
            config['do_layer'] = False
        elif o in ("-G","--no-gcode"):
            config['do_gcode'] = False
        elif o in ("-W","--no-weave"):
            config['do_weave'] = False
        elif o in ("-p","--png"):
            config['do_png'] = True
        elif o in ("-s","--slicer"):
            config['slicer'] = a
        elif o in ("--svg"):
            config['slicer'] = 'svg'
        elif o in ("--x-offset"):
            config['x_shift_mm'] = float(a) * unit[units]
        elif o in ("--y-offset"):
            config['y_shift_mm'] = float(a) * unit[units]
        elif o in ("--z-slice"):
            config['z_slice_mm'] = float(a) * unit[units]
        elif o in ("--scale"):
            config['scale'] = float(a)
        elif o in ("-o","--overspray"):
            config['sprays'] = int(a)
        elif o in ("--fuser-temp"):
            config['fuser_temp'] = float(a)
        elif o in ("--units"):
            if not units in unit:
                usage()
                sys.exit(1)
            units = a
        else:
            assert False, ("unhandled option: %s" % o)

    if len(args) != 1:
        usage()
        sys.exit(1)

    config['scale'] = config['scale'] * unit[units]

    temp_svg = tempfile.NamedTemporaryFile()

    if config['slicer'] == "slic3r":
        slicer_args = ["slic3r",
                            "--export-svg",
                            "--output", temp_svg.name,
                            "--layer-height", str(config['z_slice_mm']),
                            "--nozzle-diameter", str(config['z_slice_mm'] * 1.1),
                            "--scale", str(config['scale']),
                            args[0]]
    elif config['slicer'] == "repsnapper":
        slicer_args = ["repsnapper",
                            "-t",
                            "-i", args[0],
                            "--svg", temp_svg.name]
    elif config['slicer'] == "svg":
        slicer_args = None
    else:
        usage()
        sys.exit(1)

    # Slice STL/AMF into SVG
    if slicer_args == None:
        # User gave us an SVG file instead of STL
        svg_file = args[0]
    else:
        # Break the STL into layers
        rc = subprocess.call(slicer_args, stdout=sys.stderr)
        if rc != 0:
            sys.exit(rc)

        # Parse the SVG file
        svg_file = temp_svg.name

    # Parse milti-layer SVG file
    svg = minidom.parse(svg_file)

    max_z_mm = None
    z_mm = []
    n = 0
    for layer in svg.getElementsByTagName("g"):
        max_z_mm = group_z(layer)
        z_mm.append(max_z_mm)
        n = n + 1

    n_total = n
    brundle_prep(args[0], max_z_mm, n)

    n = 0
    for layer in svg.getElementsByTagName("g"):
        gc(None, "M117 Slice %d of %d" % ((n+1), n_total))
        if n > 1:
            this_layer_mm = z_mm[n] - z_mm[n - 1]
        else:
            this_layer_mm = 1
        if n < (len(z_mm) - 1):
            next_layer_mm = z_mm[n + 1] - z_mm[n]
        else:
            next_layer_mm = 1
        group_to_slice(layer, n, this_layer_mm, next_layer_mm)
        n = n + 1

if __name__ == "__main__":
    main()
