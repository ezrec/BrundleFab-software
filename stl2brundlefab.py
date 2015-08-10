#!/usr/bin/env python
# Copyright 2015, Jason S. McMullan <jason.mcmullan@gmail.com>
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

import re
import sys
import cairo
import numpy
import getopt
import tempfile
import subprocess
from xml.dom import minidom

X_FEED_MIN=0        # Start of feed blade pass
X_FEED_MAX=365      # End of feed blade pass

SPREAD_FEED=3000    # Spread rate while depositing the layer
INK_FEED=4          # Number of sprays per dotline
POWDER_FEED=4500    # Extruder feed rate (mm/minute)
FUSER_FEED=1500     # Fuser pass rate (mm/minute)
X_DPI=96.0
Y_DPI=96.0

Y_DOTS=12

def brundle_prep(name, max_z_mm):
    print """
; Print %s to the BrundleFab
G21 ; Units are mm
G90 ; Absolute positioning
M117 Prepare
;M1 ; Let the use make sure we're ready to home axes
G28 X0 Y0 E0 ; Home print axes
; NOTE: Z is _not_ homed, as it may be part of a multi-file print
M117 Fill %dmm
M0 ; Wait for manual fill operation
M117 ; Clear status message
T1 S%d ; Ink spray rate (dots/minute)
; Print as we feed powder
""" % (name, int(max_z_mm), INK_FEED)

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

    print "G1 X%.3f" % (in2mm(x_dots / X_DPI))
    print "T1 P0"
    print "G0 Y%.3f" % (in2mm(origin / Y_DPI))
    for i in range(origin+1, w_dots):
        if (toolmask[origin] != toolmask[i]) or (i == w_dots - 1):
            if (i == w_dots - 1) and (toolmask[origin] == 0):
                break
            print "T1 P%d" % (toolmask[origin])
            print "G0 Y%.3f" % (in2mm((i - 1) / Y_DPI))
            origin = i

    # Switching to tool 0 will cause a forward flush of the
    # inkbar, and the ink head will end up at the end of the
    # line.
    print "T0"

    # For interweave support, we advance X by a half-dot, and
    # cover the dost inbetween the forward pass on the
    # reverse pass
    if weave:
        print "G1 X%.3f" % (in2mm((x_dots + 0.5) / X_DPI))

    # Switch back to T1 to ink on the reverse movement of
    # then inkbar
    print "T1"
    print "G0 Y0"


def brundle_layer(w_dots, h_dots, surface, weave=True):
    stride = surface.get_stride()
    image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
    image = numpy.reshape(image, (stride, h_dots))
    image = numpy.greater(image, 0)

    y = 0
    for dotline in numpy.vsplit(image, h_dots/Y_DOTS):
        toolmask = numpy.zeros((stride))
        for l in range(0, Y_DOTS):
            toolmask = toolmask + dotline[l]*(1 << l)
        brundle_line(y, w_dots, toolmask, weave)
        y = y + Y_DOTS

def brundle_layer_prep(extrude_delta_mm):
    print """
; Perform pre-layer operations
G0 X%.3f Y0 ; Move to feed start
G91 ; Relative positioning
G1 E%.3f F%d; Extrude a feed layer
G90 ; Absolute positioning
; Print as we feed powder
""" % (X_FEED_MIN, extrude_delta_mm, POWDER_FEED)

def brundle_layer_finish(z_delta_mm):
    print """
; Perform post-layer operations
T0 ; Select no tool
G1 X%.3f F%d ; Finish the layer deposition
G91 ; Relative positioning
G0 Z%.3f; Drop the build layer
G90 ; Absolute positioning
T20 ; Select heat lamp tool
G1 X0 F%d; Fuse the layer
T0 ; Select no tool
""" % (X_FEED_MAX, SPREAD_FEED, z_delta_mm, FUSER_FEED)


def draw_path(config, cr, poly):
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

def group_z(config, layer):
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

def group_to_slice(config, layer, n, last_z_mm = None):
    # Create a new cairo surface
    w_dots = int(mm2in(config['y_bound_mm']) * Y_DPI)
    h_dots = int(mm2in(config['x_bound_mm']) * X_DPI)

    if (h_dots % Y_DOTS) != 0:
        h_dots = int((h_dots + Y_DOTS - 1) / Y_DOTS) * Y_DOTS

    surface = cairo.ImageSurface(cairo.FORMAT_A8, w_dots, h_dots)
    cr = cairo.Context(surface)
    cr.set_antialias(cairo.ANTIALIAS_NONE)

    z_mm = group_z(config, layer)
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
        draw_path(config, cr, contour)
        cr.fill()

    # Draw holes
    cr.set_operator(cairo.OPERATOR_CLEAR)
    for hole in holes:
        draw_path(config, cr, hole)
        cr.fill()

    # Emit the image
    surface.flush()
    if config['do_png']:
        surface.write_to_png("layer-%03d.png" % n)
    if config['do_extrude'] and last_z_mm != None:
        brundle_layer_finish(z_mm - last_z_mm)
        brundle_layer_prep(z_mm - last_z_mm)
    if config['do_layer']:
        brundle_layer(w_dots, h_dots, surface, weave=config['do_weave'])

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
  --scale N             Scale object (before offsetting)
  --x-offset N          Add a X offset (in mm) to the layers
  --y-offset N          Add a Y offset (in mm) to the layers

GCode output:
  -G, --no-gcode        Do not generate any GCode (assumes S, E, and L)
  -S, --no-startup      Do not generate GCode startup code
  -L, --no-layer        Do not generate layer inking commands
  -W, --no-weave        Do not generate interweave commands
  -E, --no-extrude      Do not generate E or Z axis commands
  -p, --png             Generate 'layer-XXX.png' files, one for each layer

"""

def main():
    config = {}
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

    try:
        opts, args = getopt.getopt(sys.argv[1:], "EGhLps:SW", ["help","no-gcode","no-extrude","no-layer","png","no-startup","no-weave","slicer=","svg","x-offset=","y-offset=","z-slice=","scale="])
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
            config['x_shift_mm'] = float(a)
        elif o in ("--y-offset"):
            config['y_shift_mm'] = float(a)
        elif o in ("--z-slice"):
            config['z_slice_mm'] = float(a)
        elif o in ("--scale"):
            config['scale'] = float(a)
        else:
            assert False, ("unhandled option: %s" % o)

    if len(args) != 1:
        usage()
        sys.exit(1)

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
        max_z_mm = group_z(config, layer)

    if config['do_startup']:
        brundle_prep(args[0], max_z_mm)

    last_z_mm = None
    z_mm = None
    n = 0
    for layer in svg.getElementsByTagName("g"):
        last_z_mm = z_mm
        z_mm = group_to_slice(config, layer, n, last_z_mm)
        n = n + 1

    # Finish the last layer
    if config['do_extrude']:
        brundle_layer_finish(z_mm - last_z_mm)


if __name__ == "__main__":
    main()
