#!/usr/bin/env python

import sys
import getopt
import array
import cairo
import re
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

X_DOTS=12
Y_DOTS=12

MM_TO_DOTS = X_DPI / 25.4

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

def mm(inch):
    return inch * 25.4

def brundle_line(x_dots, w_dots, toolmask):
    origin = None
    for i in range(0, w_dots):
        if toolmask[i] != 0:
            origin = i
            break
    if origin == None:
        return

    print "T0"
    print "G0 X%.3f Y%.3f" % (mm(x_dots / X_DPI), mm(origin / Y_DPI))
    for i in range(origin+1, w_dots):
        if (toolmask[origin] != toolmask[i]) or (i == w_dots - 1):
            if (i == w_dots - 1) and (toolmask[origin] == 0):
                break
            print "T1 P%d" % (toolmask[origin])
            print "G1 Y%.3f" % (mm((i - 1) / Y_DPI))
            origin = i
    print "G0 Y0"


def brundle_layer(z_mm, w_dots, h_dots, surface):
    image = surface.get_data()
    stride = surface.get_stride()
    for y in range(0,h_dots,Y_DOTS):
        toolmask = array.array('H', '\000' * w_dots * 2)
        for x in range(0,w_dots):
            for l in range(0, X_DOTS):
                val = ord(image[x + (y+l) * stride])
                if val != 0:
                    toolmask[x] = toolmask[x] | (1 << l)
        brundle_line(y, w_dots, toolmask)

    print """
; Perform post-layer operations
T0 ; Select no tool
G28 Y0 ; Reset ink head position
G1 X%.3f F%d ; Finish the layer deposition
G0 Z%.3f; Drop the build layer
T20 ; Select heat lamp tool
G1 X0 %d; Dry the layer
T0 ; Select no tool
G0 X%.3f Y0 ; Move to feed start
G1 E%.3f F%d; Extrude a feed layer
G28 X0 ; Re-home the X axis
; Print as we feed powder
""" % (X_FEED, SPREAD_FEED, z_mm, DRY_FEED, X_MIN, z_mm, POWDER_FEED)


def draw_path(cr, poly):
    p = poly.getAttribute("points")
    p = re.sub(r'\s+',r' ', p)
    p = re.sub(r' *, *',r' ', p)
    pairs = zip(*[iter(p.split(' '))]*2)

    moved = False
    for pair in pairs:
        point=[float(f) for f in pair]
        if moved:
            cr.line_to(point[0], point[1])
        else:
            cr.move_to(point[0], point[1])
            moved = True
    cr.close_path()

def group_to_slice(w_dots, h_dots, layer, n, scale = MM_TO_DOTS):
    # Create a new cairo surface
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
    cr.scale(scale, scale)

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
    #surface.write_to_png("layer-%03d.png" % n)
    brundle_layer(z_mm, w_dots, h_dots, surface)

def usage():
    pass


def main():
    w_dots = int(8.75 * Y_DPI)
    h_dots = int(8 * X_DPI)
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hz:", ["help","z-slice="])
    except getopt.GetoptError as err:
        print(err)
        usage()
        sys.exit(2)
    z_step = 0.5 #mm
    for o, a in opts:
        if o in ("-h", "--help"):
            usage()
            sys.exit()
        elif o in ("-z", "--z-slice"):
            z_step = a
        else:
            assert False, ("unhandled option: %s" % o)

    svg = minidom.parse(args[0])

    # Break the STL into layers
    n = 0
    brundle_prep(args[0])
    for layer in svg.getElementsByTagName("g"):
        group_to_slice(w_dots, h_dots, layer, n)
        n = n + 1


if __name__ == "__main__":
    main()
