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
    return inch * 25.4

def mm2in(mm):
    return mm / 25.4

class Fab(object):
    """ Base printer class """

    def __init__(self, output = None, log = None ):
        self.log = log
        self.output = output
        self.svg = None
        pass

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
        self.send(comment = "Prepare, job %s" % (name), code = None)
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
        self.svg = xml
        self.dot_h = 1000
        self.dot_v = 1000
        self.dpi_h = 300
        self.dpi_v = 300
        self.shift_h = 0
        self.shift_v = 0
        self.z = []

        for layer in self.svg.getElementsByTagName("g"):
            self.z.append((self._group_z(layer), layer, None))

        # Sort by Z
        self.z.sort()
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
        if layer >= len(self.z):
            return self.z[len(self.z)-1][0]
        else:
            return self.z[layer][0]

    def height_mm(self, layer = 0):
        z_mm = self.z_mm(layer)
        if layer == 0:
            height_mm = z_mm
        else:
            height_mm = z_mm - self.z[layer-1][0]
        return height_mm

    # Return number of layers
    def layers(self):
        return len(self.z)

    def _surface_cache_flush(self):
        for z in self.z:
            z = (z[0], z[1], None)
            pass
        pass

    # Returns the size, in dots
    def size(self, dot_h = None, dot_v = None, mm_h = None, mm_v = None, in_h = None, in_v = None):
        if in_h is not None:
            self.dot_h = int(in_h * self.dpi_h)
        if in_v is not None:
            self.dot_v = int(in_v * self.dpi_v)
        if mm_h is not None:
            self.dot_h = int(mm2in(mm_h) * self.dpi_h)
        if mm_v is not None:
            self.dot_v = int(mm2in(mm_v) * self.dpi_v)
        if dot_h is not None:
            self.dot_h = dot_h
        if dot_v is not None:
            self.dot_v = dot_v

        self._surface_cache_flush()
        return (self.dot_h, self.dot_v)

    def offset(self, dot_h = None, dot_v = None, mm_h = None, mm_v = None, in_h = None, in_v = None):
        if in_h is not None:
            self.shift_h = int(in_h * self.dpi_h)
        if in_v is not None:
            self.shift_v = int(in_v * self.dpi_v)
        if mm_h is not None:
            self.shift_h = int(mm2in(mm_h) * self.dpi_h)
        if mm_v is not None:
            self.shift_v = int(mm2in(mm_v) * self.dpi_v)
        if dot_h is not None:
            self.shift_h = dot_h
        if dot_v is not None:
            self.shift_v = dot_v

        self._surface_cache_flush()
        return (self.shift_h, self.shift_v)

    # Set up the resolution
    def resolution(self, dpi = None, dpi_h = None, dpi_v = None):
        if dpi is not None:
            self.dpi_h = dpi
            self.dpi_v = dpi
        if dpi_h is not None:
            self.dpi_h = dpi_h
        if dpi_v is not None:
            self.dpi_v = dpi_v

        self._surface_cache_flush()
        return (self.dpi_h, self.dpi_v)

    def _draw_path(self, cr, poly):
        x_shift = in2mm(self.shift_h/self.dpi_h)
        y_shift = in2mm(self.shift_v/self.dpi_v)
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
        z_mm, svg, surface = self.z[layer]

        if surface is not None:
            return surface

        height_mm = self.height_mm(layer)

        # Create a new cairo surface
        surface = cairo.ImageSurface(cairo.FORMAT_A8, self.dot_h, self.dot_v)
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
        cr.scale(mm2in(1.0) * self.dpi_h, mm2in(1.0) * self.dpi_v)

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
        self.z[layer] = (z_mm, svg, surface)

        return surface


#  vim: set shiftwidth=4 expandtab: # 
