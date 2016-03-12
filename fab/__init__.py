# 
#  Copyright (C) 2016, Jason S. McMullan <jason.mcmullan@gmail.com>
#  All rights reserved.
# 
#  Licensed under the MIT License:
# 
#  Permission is hereby granted, free of charge, to any person obtaining
#  a copy of this software and associated documentation files (the "Software"),
#  to deal in the Software without restriction, including without limitation
#  the rights to use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of the Software, and to permit persons to whom the
#  Software is furnished to do so, subject to the following conditions:
# 
#  The above copyright notice and this permission notice shall be included
#  in all copies or substantial portions of the Software.
# 
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
#  FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#  DEALINGS IN THE SOFTWARE.
#

__all__ = ['posjet', 'brundle']

import re
import cairo
import numpy

# Convenience functions
def in2mm(inch):
    if inch is None:
        return 0
    return inch * 25.4

def mm2in(mm):
    if mm is None:
        return 0
    return mm / 25.4

class Fab(object):
    """ Base printer class """

    def __init__(self, output = None, log = None ):
        self.log = log
        self.output = output
        self.svg = None
        pass

    # MUST OVERRIDE: Return the (x, y, z) mm dimenstions of the bed
    def size_mm(self):
        return (200.0, 200.0, 200.0)

    # Write something to the output
    def send(self, comment = None, code = None ):
        if comment is not None and self.log is not None:
            self.log.write("#%s\n" % (comment))
        if code is not None and self.output is not None:
            self.output.write(code)
        pass

    def layers(self):
        if self.svg is not None:
            return self.svg.layers()
        return 0

    # Prepare for the first layer
    def prepare(self, svg = None, name = None, config = None):
        self.config = config
        self.svg = svg

        size_mm = list(self.size_mm())
        if 'x_bound_mm' in config:
            size_mm[0] = min(config['x_bound_mm'], size_mm[0])
        if 'y_bound_mm' in config:
            size_mm[1] = min(config['y_bound_mm'], size_mm[1])
        svg.size_mm(mm = size_mm)

        shift_mm = [0] * 2
        if 'x_shift_mm' in config:
            shift_mm[0] = min(config['x_shift_mm'], size_mm[0])
        if 'y_shift_mm' in config:
            shift_mm[1] = min(config['y_shift_mm'], size_mm[1])
        svg.offset_mm(mm = shift_mm)

        layers = self.layers()
        z_mm = svg.z_mm(layers)

        self.send(comment = "Prepare job '%s', %d layers, %.2fmm" % (name, layers, z_mm), code = None)
        pass

    # Render a layer
    # 'z' is float in units of mm
    # 'height' is a float in units of mm
    # 'surface' is a cairo ARGB surface
    def render(self, layer = 0):
        z = self.svg.z(layer)
        self.send(comment = "Layer %d at %dmm" % (layer, z), code = None)
        pass

    # Clean up after the last layer
    def finish(self):
        self.send(comment = "Finish", code = None)
        pass

class SVGRender(object):
    """ SVG Rendering helpers """

    def __init__(self, xml = None):
        self._svg = xml
        self._dpi = [300] * 2
        self._size = [200] * 2
        self._shift = [0] * 2
        self._z = []

        for layer in self._svg.getElementsByTagName("g"):
            self._z.append((self._group_z(layer), layer, None))

        # Sort by Z
        self._z.sort()
        pass

    # Determine Z value of a layer of the SVG
    def _group_z(self, svg_layer):
        z_mm = None
        if svg_layer.hasAttribute("slic3r:z"):
            # slic3r
            z_mm = float(svg_layer.getAttribute("slic3r:z")) * 1000000
        else:
            # repsnapper
            label = svg_layer.getAttribute("id").split(':')
            if len(label) != 2:
                return
            z_mm = float(label[1])
        return z_mm

    def z_mm(self, layer = 0):
        if layer >= len(self._z):
            return self._z[len(self._z)-1][0]
        else:
            return self._z[layer][0]

    def height_mm(self, layer = 0):
        z_mm = self.z_mm(layer)
        if layer == 0:
            height_mm = z_mm
        else:
            height_mm = z_mm - self._z[layer-1][0]
        return height_mm

    # Return number of layers
    def layers(self):
        return len(self._z)

    def _surface_cache_flush(self):
        for z in self._z:
            z = (z[0], z[1], None)
            pass
        pass

    def _any2mm(self, ref = None, mm = None, inch = None):
        if inch is not None:
            mm = [ in2mm(x) for x in inch]
            pass

        if mm is not None:
            changed = False
            for i in range(0, 2):
                if mm[i] is not None and mm[i] > 0:
                    ref[i] = mm[i]
                    changed = True
                    pass
                pass
            return changed

        return False

    # Return the size, in mm
    def size_mm(self, mm = None, inch = None):
        if self._any2mm(ref = self._size, mm = mm, inch = inch):
            self._surface_cache_flush()

        return tuple(self._size)

    # Return the size, in dots
    def size(self):
        return tuple([int(mm2in(self._size[i])*self._dpi[i]) for i in range(0,2)])

    def offset_mm(self, mm = None, inch = None):
        if self._any2mm(ref = self._shift, mm = mm, inch = inch):
            self._surface_cache_flush()

        return tuple(self._shift)

    # Set up the resolution in dpi
    def resolution(self, dpi = None):
        if self._any2mm(ref = self._dpi, mm = dpi):
            self._surface_cache_flush()

        return tuple(self._dpi)

    def _draw_path(self, cr, poly):
        x_shift = in2mm(self._shift[0]/self._dpi[0])
        y_shift = in2mm(self._shift[1]/self._dpi[1])
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

    # Return the (float(z_mm), float(height_mm), cairo.ImageSurface(surface))
    # of a layer
    def surface(self, layer = 0):
        z_mm, svg, surface = self._z[layer]

        if surface is not None:
            return surface

        height_mm = self.height_mm(layer)

        # Create a new cairo surface
        dot = self.size()

        surface = cairo.ImageSurface(cairo.FORMAT_A8, dot[0], dot[1])
        cr = cairo.Context(surface)
        cr.set_antialias(cairo.ANTIALIAS_NONE)

        contours = []
        holes = []
        for poly in svg.getElementsByTagName("polygon"):
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
        cr.scale(mm2in(1.0) * self._dpi[0], mm2in(1.0) * self._dpi[1])

        # Draw filled area
        for contour in contours:
            self._draw_path(cr, contour)
            cr.fill()

        # Draw holes
        cr.set_operator(cairo.OPERATOR_CLEAR)
        for hole in holes:
            self._draw_path(cr, hole)
            cr.fill()

        # Emit the image
        surface.flush()

        # Update the layer info
        self._z[layer] = (z_mm, svg, surface)

        return surface

import fab.brundle
import fab.posjet
import fab.tmc600

fabricator = {
        'brundle': fab.brundle,
        'posjet' : fab.posjet,
        'tmc600' : fab.tmc600,
        }

#  vim: set shiftwidth=4 expandtab: # 
