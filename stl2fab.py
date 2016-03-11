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

import fab
import fab.brundle

def usage():
    print("""
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

""")
    pass

def main(out = None, log = None):
    config = {}

    config['gcode_terse'] = False
    config['fuser_temp'] = 0.0      # Celsius
    config['sprays'] = 6            # Sprays per pixel
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
    svg = fab.SVGRender(xml = minidom.parse(svg_file))

    printer = fab.brundle.Fab(output = out, log = log)

    printer.prepare(svg = svg, name = args[0], config = config)

    for layer in range(0, printer.layers()):
        if config['do_png']:
            surface = printer.surface(layer)
            surface.write_to_png("layer-%03d.png" % layer)

        printer.layer(layer = layer)
        pass

    printer.finish()

    pass


if __name__ == "__main__":
    try:
        # Python3
        out = sys.stdout.buffer
    except:
        out = sys.stdout
    log = sys.stderr
    main(out = out, log = log)
