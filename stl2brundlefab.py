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
# 2. The Feed Bin raises by one layer width, Part Bin lowers by one width
# 3. The layer head advances in X until the the fuser (F) is at the start
#    at the start of Part Bin.
# 4. The fuser is enabled, and brought up to temperature.
# 5. The layer head advances in X, depositing fresh powder onto the newly
#    fused layer, until the the fuser (F) is at the start of the Waste Bin
# 6. The fuser is disabled.
# 7. The layer head advances in X, until the repowder blade (R) is at the
#    start of the Waste Bin
# 8. The Part Bin (Z) and the Feed Bin (E) both drop by 1mm.
#    This is needed so that the repowder blade will not disturb the existing
#    powder layer during the inking pass.
# 9. The layer head retracts in X until the ink head (H) is at the end
#    of the Part Bin.
# 10.The ink deposition phase then begins, depositing ink on the
#    fresh powder layer, as the layer head retracts in X.
# 11.The layer head is fully retraced.
#    This will position the repowder blade (R) at the start of the powder
#    feed bin.
# 12.The Feed Bin raises by 1mm, the Part Bin raises by 1mm
#
# Repeat steps 1 - 12 for all layers. A final 'no ink' layer is inserted
# after the last printed layer to ensure compete fusing.

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

FEED_SPREAD=3000    # Spread rate while depositing the layer
FEED_INK=4          # Number of sprays per dotline
FEED_POWDER=4500    # Extruder feed rate (mm/minute)
FEED_FUSER=750     # Fuser pass rate (mm/minute)
X_DPI=96.0
Y_DPI=96.0

Y_DOTS=12

config = {}
config['gcode_terse'] = False
config['fuser_temp'] = 0.0      # Celsius

def gc(comment, code = None):
    if config['gcode_terse']:
        comment = None

    if comment == None and code != None:
        print "%s" % (code)
    elif code != None:
        print "%s ; %s" % (code, comment)
    elif comment != None:
        print "; %s" % (comment)
    pass

def brundle_prep(name, max_z_mm):
    gc("Print %s to the BrundleFab" % name)
    gc("Units are mm", "G21")
    gc("Absolute positioning", "G90")
    gc("Set pen tool offset", "G10 L1 P1 X%.3f" % (X_OFFSET_PEN))
    gc("Set fuser tool offset", "G10 L1 P20 X%.3f" % (X_OFFSET_FUSER))
    gc("Set repowder blade offset", "G10 L1 P21 X%.3f" % (X_OFFSET_RECOAT))

    gc(None, "M117 Ready to home")
    gc("Let the user make sure we're ready to home axes", "M0")
    gc("Home print axes", "G28 X0 Y0 E0")
    gc("NOTE: Z is _not_ homed, as it may be part of a multi-file print")
    gc(None, "M117 Fill %dmm" % (int(max_z_mm)))
    gc("Wait for manual fill operation", "M0")
    gc("Clear status message", "M117")
    gc("Ink spray rate (sprays/dot)", "T1 S%d" % (FEED_INK))

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

    gc(None, "G1 X%.3f" % (X_BIN_PART + in2mm(x_dots / X_DPI)))
    gc(None, "T1 P0")
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
    gc(None, "T1 P0")

    # For interweave support, we retract X by a half-dot, and
    # cover the dots inbetween the forward pass on the
    # reverse pass
    if weave:
        gc(None, "G1 X%.3f" % (X_BIN_PART + in2mm((x_dots - 0.5) / X_DPI)))

    # Switch back to T1 to ink on the reverse movement of
    # then inkbar
    gc(None, "G1 Y0")


# Note: h_dots _must_ be a multiple of Y_DOTS!
def brundle_layer(w_dots, h_dots, surface, weave=True):
    if not config['do_layer']:
        return

    stride = surface.get_stride()
    image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
    image = numpy.reshape(image, (stride, h_dots))
    image = numpy.greater(image, 0)

    # Issue the printbars in reverse order, since
    # we are drawing in the negiative X direction
    y = h_dots - Y_DOTS
    dotlines = numpy.vsplit(image, h_dots/Y_DOTS)
    list.reverse(dotlines)
    for dotline in dotlines:
        toolmask = numpy.zeros((stride))
        for l in range(0, Y_DOTS):
            toolmask = toolmask + dotline[l]*(1 << l)
        brundle_line(y, w_dots, toolmask, weave)
        y = y - Y_DOTS

def brundle_layer_prep(e_delta_mm, z_delta_mm):
    if not config['do_extrude']:
        return

    gc("1. Assume layer head is at feed start")
    gc("2. Raise Feed Bin by one layer width, lower Part bin")
    gc(  "Relative positioning", "G91")
    gc(  "Extrude a feed layer", "G1 E%.3f Z%.3f F%d" % (e_delta_mm, z_delta_mm, FEED_POWDER))
    gc(  "Absolute positioning", "G90")
    gc("3. Select fuser, and advance to Part Bin start")
    gc(  "Select fuser, but unlit", "T20 P0")
    gc(  "Advance to Part Bin start", "G1 X%.3f F%d" % (X_BIN_PART, FEED_SPREAD))
    gc("4. The fuser is enabled, and brought up to temp")
    gc(  "Select fuser and temp", "T20 P%.3f" % (config['fuser_temp']))
    gc(  "Wait for fuser to reach target temp", "M116 P20")
    gc("5. Advance fuser to start of Waste Bin")
    gc(  "Fuse and recoat...", "G1 X%.3f F%d" % (X_BIN_WASTE, FEED_FUSER))
    gc("6. The fuser is disabled")
    gc(  "Select recoat tool", "T21")
    gc("7. Advance recoat blade to Waste Bin")
    gc(  "Advance to waste bin", "G1 X%.3f F%d" % (X_BIN_WASTE, FEED_SPREAD))
    gc("8. Drop Part Bin and Feed Bin by 1mm")
    gc(  "Relative positioning", "G91")
    gc(  "Drop bins by 1mm", "G1 E-1 Z1 F%d" % (FEED_POWDER))
    gc(  "Absolute positioning", "G90")
    gc("9. Move pen to end of the part bin")
    gc(  "Select ink tool", "T1 P0")
    gc(  "Move pen to end of the part bin", "G0 X%.3f" % (X_BIN_WASTE))
    gc("10. Ink the layer")
    # See brundle_layer()

def brundle_layer_finish():
    if not config['do_extrude']:
        return

    gc("11. Retract recoating blade to start of the Feed Bin")
    gc(  "Select the recoating tool", "T21")
    gc(  "Move to start", "G0 X%.3f Y0" % (X_BIN_FEED))
    gc("12. The Feed Bin raises by 1mm,")
    gc("    the Part Bin raises by 1mm")
    gc(  "Relative positioning", "G91")
    gc(  "Raise the bins", "G1 E1 Z-1 F%d" % (FEED_POWDER))
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

def group_to_slice(layer, n, last_z_mm = None):
    # Create a new cairo surface
    w_dots = int(mm2in(config['y_bound_mm']) * Y_DPI)
    h_dots = int(mm2in(config['x_bound_mm']) * X_DPI)

    if (h_dots % Y_DOTS) != 0:
        h_dots = int((h_dots + Y_DOTS - 1) / Y_DOTS) * Y_DOTS

    surface = cairo.ImageSurface(cairo.FORMAT_A8, w_dots, h_dots)
    cr = cairo.Context(surface)
    cr.set_antialias(cairo.ANTIALIAS_NONE)

    z_mm = group_z(layer)
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

    if last_z_mm == None:
        layer_mm = 0
    else:
        layer_mm = z_mm - last_z_mm

    brundle_layer_prep(layer_mm, layer_mm)
    brundle_layer(w_dots, h_dots, surface, weave=config['do_weave'])
    brundle_layer_finish()

    return z_mm

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
  -E, --no-extrude      Do not generate E or Z axis commands
  -p, --png             Generate 'layer-XXX.png' files, one for each layer

"""

def main():
    config['x_bound_mm'] = 200.0
    config['y_bound_mm'] = 200.0
    config['x_shift_mm'] = 0.0
    config['y_shift_mm'] = 0.0
    config['z_slice_mm'] = 0.5
    config['scale'] = 1.0
    config['do_png'] = False
    config['do_startup'] = True
    config['do_layer'] = True
    config['do_extrude'] = True
    config['do_weave'] = True
    config['slicer'] = 'slic3r'

    unit = {}
    unit['mm'] = 1.0
    unit['in'] = 25.4
    unit['ti'] = 2.54   # Tenths of inches

    units = 'mm'

    try:
        opts, args = getopt.getopt(sys.argv[1:], "EGhLps:SW", ["help","no-gcode","no-extrude","no-layer","png","no-startup","no-weave","slicer=","svg","x-offset=","y-offset=","z-slice=","scale=","fuser-temp=","units="])
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
        elif o in ("-L","--no-layer"):
            config['do_layer'] = False
        elif o in ("-G","--no-gcode"):
            config['do_startup'] = False
            config['do_layer'] = False
            config['do_extrude'] = False
        elif o in ("--no-weave"):
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
    for layer in svg.getElementsByTagName("g"):
        max_z_mm = group_z(layer)

    if config['do_startup']:
        brundle_prep(args[0], max_z_mm)

    last_z_mm = None
    z_mm = None
    n = 0
    for layer in svg.getElementsByTagName("g"):
        last_z_mm = z_mm
        z_mm = group_to_slice(layer, n, last_z_mm)
        n = n + 1

    # Fuse top layer
    brundle_layer_prep(0, 1)
    brundle_layer_finish()


if __name__ == "__main__":
    main()
