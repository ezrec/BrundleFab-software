#!/usr/bin/env python

import re
import sys
import cairo
import numpy
import getopt
import tempfile
import subprocess
from xml.dom import minidom

X_MIN=-195
X_MAX=180
X_FEED=365

SPREAD_FEED=3000
INK_FEED=1
POWDER_FEED=4500
DRY_FEED=3000
X_DPI=96.0
Y_DPI=96.0

Y_DOTS=12

def brundle_prep(name):
    print """
; Print %s to the BrundleFab
G21 ; Units are mm
G90 ; Absolute positioning
M117 Prepare
;M1 ; Let the use make sure we're ready to home axes
G28 X0 Y0 ; Home print axes
M117 Fill powder
;M0 ; Wait for manual fill operation
M117 ; Clear status message
T1 S%d ; Ink spray rate (dots/minute)
T0 ; Select no tool
; Print as we feed powder
""" % (name, INK_FEED)

def in2mm(inch):
    return inch * 25.4

def mm2in(mm):
    return mm / 25.4

def brundle_line(x_dots, w_dots, toolmask):
    origin = None
    for i in range(0, w_dots):
        if toolmask[i] != 0:
            origin = i
            break
    if origin == None:
        return

    print "T0"
    print "G0 X%.3f Y%.3f" % (in2mm(x_dots / X_DPI), in2mm(origin / Y_DPI))
    for i in range(origin+1, w_dots):
        if (toolmask[origin] != toolmask[i]) or (i == w_dots - 1):
            if (i == w_dots - 1) and (toolmask[origin] == 0):
                break
            print "T1 P%d" % (toolmask[origin])
            print "G1 Y%.3f" % (in2mm((i - 1) / Y_DPI))
            origin = i
    print "G0 Y0"


def brundle_layer(z_mm, w_dots, h_dots, surface):
    stride = surface.get_stride()
    image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
    image = numpy.reshape(image, (stride, h_dots))
    image = numpy.greater(image, 0)

    y = 0
    for dotline in numpy.vsplit(image, Y_DOTS):
        toolmask = numpy.zeros((stride))
        for l in range(0, Y_DOTS):
            toolmask = toolmask + dotline[l]*(1 << l)
        brundle_line(y, w_dots, toolmask)
        y = y + Y_DOTS

def brundle_extrude(z_mm):
    print """
; Perform post-layer operations
T0 ; Select no tool
G1 X%.3f F%d ; Finish the layer deposition
G0 Z%.3f; Drop the build layer
T20 ; Select heat lamp tool
G1 X0 %d; Dry the layer
T0 ; Select no tool
G0 X%.3f Y0 ; Move to feed start
G1 E%.3f F%d; Extrude a feed layer
; Print as we feed powder
""" % (X_FEED, SPREAD_FEED, z_mm, DRY_FEED, X_MIN, z_mm, POWDER_FEED)


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

def group_to_slice(config, layer, n):
    # Create a new cairo surface
    w_dots = int(mm2in(config['y_bound_mm']) * Y_DPI)
    h_dots = int(mm2in(config['x_bound_mm']) * X_DPI)

    if (h_dots % Y_DOTS) != 0:
        h_dots = int((h_dots + Y_DOTS - 1) / Y_DOTS) * Y_DOTS

    surface = cairo.ImageSurface(cairo.FORMAT_A8, w_dots, h_dots)
    cr = cairo.Context(surface)
    cr.set_antialias(cairo.ANTIALIAS_NONE)

    if layer.hasAttribute("slic3r:z"):
        # slic3r
        z_mm = float(layer.getAttribute("slic3r:z")) * 1000000
    else:
        # repsnapper
        label = layer.getAttribute("id").split(':')
        if len(label) != 2:
            return
        z_mm = float(label[1])

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
    if config['do_layer']:
        brundle_layer(z_mm, w_dots, h_dots, surface)
    if config['do_extrude']:
        brundle_extrude(z_mm)

def usage():
    print """
svg2brundlefab [options] sourcefile.stl >sourcefile.gcode
svg2brundlefab [options] --svg sourcefile.svg >sourcefile.gcode

  -h, --help            This help

Input conversion:
  --svg                 Treat input as a SVG file
  -s, --slicer=SLICER   Select a slicer ('repsnapper' or 'slic3r')

Transformation:
  --x-offset N          Add a X offset (in mm) to the layers
  --y-offset N          Add a Y offset (in mm) to the layers

GCode output:
  -G, --no-gcode        Do not generate any GCode (assumes S, E, and L)
  -S, --no-startup      Do not generate GCode startup code
  -E, --no-extrude      Do not generate E or Z axis commands
  -L, --no-layer        Do not generate layer inking commands
  -p, --png             Generate 'layer-XXX.png' files, one for each layer

"""

def main():
    config = {}
    config['x_bound_mm'] = 200.0
    config['y_bound_mm'] = 200.0
    config['x_shift_mm'] = 0.0
    config['y_shift_mm'] = 0.0
    config['do_png'] = False
    config['do_startup'] = True
    config['do_layer'] = True
    config['do_extrude'] = True
    config['slicer'] = 'slic3r'

    try:
        opts, args = getopt.getopt(sys.argv[1:], "EGhLps:S", ["help","no-gcode","no-extrude","no-layer","png","no-startup","slicer=","svg","x-offset=","y-offset="])
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)
    z_step = 0.5 #mm
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
        elif o in ("-p","--png"):
            config['do_png'] = True
        elif o in ("-s","--slicer"):
            config['slicer'] = a
        elif o in ("--x-offset"):
            config['x_shift_mm'] = float(a)
        elif o in ("--y-offset"):
            config['y_shift_mm'] = float(a)
        elif o in ("--svg"):
            config['slicer'] = 'svg'
        else:
            assert False, ("unhandled option: %s" % o)

    if len(args) != 1:
        usage()
        sys.exit(1)

    temp_svg = tempfile.NamedTemporaryFile()

    if config['slicer'] == "slic3r":
        slicer_args = ["slic3r", "--export-svg", "--output", temp_svg.name, args[0]]
    elif config['slicer'] == "repsnapper":
        slicer_args = ["repsnapper", "-t", "-i", args[0], "--svg", temp_svg.name]
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
        rc = subprocess.call(slicer_args)
        if rc != 0:
            sys.exit(rc)

        # Parse the SVG file
        svg_file = temp_svg.name

    # Parse milti-layer SVG file
    svg = minidom.parse(svg_file)

    n = 0
    if config['do_startup']:
        brundle_prep(args[0])

    for layer in svg.getElementsByTagName("g"):
        group_to_slice(config, layer, n)
        n = n + 1


if __name__ == "__main__":
    main()
