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

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
import numpy
import struct
import datetime

import fab

DPI_X = 360
DPI_Y = 180
FEED_RETRACT = 2.0 # mm

BED_X = 47.5
BED_Y = 80.0
BED_Z = 40.0

BED_X_MARGIN_LEFT = 0.0 # mm 
BED_X_MARGIN_RIGHT = 1.0 # mm 

BED_Y_MARGIN_TOP = 5.0 # mm
BED_Y_MARGIN_BOTTOM = 10.0 # mm

class Fab(fab.Fab):

    def size_mm(self):
        return (BED_X, BED_Y, BED_Z)

    def send_esc(self, code = None, data = None):
        if data is None:
            data = b''
        self.send(comment = None, code = b'\033' + code + data)
        pass

    def send_escp(self, code = None, data = None):
        self.send(comment = None, code = b'\033(' + code + struct.pack("<H", len(data)) + data)
        pass

    def send_remote1(self, code = None, data = None):
        if data is None:
            data = b''
        else:
            data = b"\000" + data
        self.send(comment = None, code = code + struct.pack("<H", len(data)) + data)
        pass

    def prepare(self, svg = None, name = None, config = None):
        # Accomodate the 5mm hardware left margin
        config['x_shift_mm'] += 5.0

        super(Fab, self).prepare(svg = svg, name = name, config = config)

        # Do any start-of-day initialization here
        self.send("Leave packet mode", b'\000\000\000')
        self.send_esc(b'\001', b'@EJL 1284.4\n@EJL     \n')
        self.send_esc(b'@')
        self.send_esc(b'@')

        self.send_escp(b'R', b'\000REMOTE1')
        now = datetime.datetime.today()
        self.send_remote1(b'TI', struct.pack(">HBBBBB", now.year, now.month, now.day, now.hour, now.minute, now.second))
        self.send_remote1(b'JS', b'\000\000\000')
        job_id = 1234
        self.send_remote1(b'JH', struct.pack(">BL", 1, job_id) + b'\x34\x02\x86\x08\x00\x61')
        self.send_esc(b'\000', b'\000\000')

        self.send_escp(b'd', b'\000' * 32767)
        self.send_escp(b'd', b'\000' * 32767)
        self.send("Leave packet mode", b'\000\000\000')
        self.send_esc(b'\001', b'@EJL 1284.4\n@EJL     \n')


        self.send_escp(b'R', b'\000REMOTE1')
        self.send_remote1(b'EX', struct.pack(">LB", 5, 0)) # ???
        self.send_remote1(b'AC', b'\x01') # Enable auto-cutter
        self.send_esc(b'\000', b'\000\000')

        # Enable graphics mode
        self.send_escp(b'G', b'\001')

        # Set resolution
        svg.resolution(dpi = (DPI_X, DPI_Y))
        dots_h, dots_v = svg.size()
        unit = 1440
        page = unit / DPI_Y
        vertical = unit / DPI_Y
        horizontal = unit / DPI_X
        self.send_escp(b'U', struct.pack("<BBBH", page, vertical, horizontal, unit))

        self.margin_left = int(fab.mm2in(BED_X_MARGIN_LEFT) * DPI_X)
        self.margin_right = int(fab.mm2in(BED_X_MARGIN_RIGHT) * DPI_X)
        self.margin_top = int(fab.mm2in(BED_Y_MARGIN_TOP) * DPI_Y)
        self.margin_bottom = int(fab.mm2in(BED_Y_MARGIN_BOTTOM) * DPI_Y)

        # Set paper loading/ejection
        self.send_esc(b'\x19', b'1')
        # Set page length
        self.send_escp(b'C', struct.pack("<L", self.margin_top + dots_v + self.margin_bottom))
        # Set page top & bottom
        self.send_escp(b'c', struct.pack("<LL", self.margin_top, self.margin_top + dots_v))
        pass

    def _render_lines(self, raster = None, microweave = False):
        lines = len(raster)
        bwidth = len(raster[0])

        if lines == 0:
            return

        if microweave:
            bitmap = bytearray([]).join([raster[i] for i in range(0, lines, 2)])
            weaved = bytearray([]).join([raster[i] for i in range(1, lines, 2)])
            lines //= 2
        else:
            bitmap = bytearray([]).join(raster)

        cmode = 0
        bpp = 2 # 2 bits/pixel

        for color in [2, 1, 4]:
            cmd = struct.pack("<BBBHH", color, cmode, bpp, bwidth, lines )
            if self.margin_left > 0:
                self.send_escp(b'$', struct.pack("<L", self.margin_left))

            self.send_esc(b'i', cmd + bitmap)

            if microweave:
                self.send_escp(b'$', struct.pack("<L", self.margin_left))
                cmd = struct.pack("<BBBHH", color | 0x40, cmode, bpp, bwidth, lines )
                self.send_esc(b'i', cmd + weaved)

            self.send(code = b'\r')
            pass
        pass

    def render(self, layer = 0):
        config = self.config
        z_delta_mm = self.svg.height_mm(layer)
        e_delta_mm = z_delta_mm * 1.1;

        self.send("1. Assume layer head is at feed start")

        if config['do_extrude']:
            self.send("2. Raise Feed Bin by one layer width")
            self.send("3. Advance recoat blade past Waste Bin")
            self.send("4. Drop Part Bin by %.3fmm, and Feed Bin by %.3fmm" % (FEED_RETRACT, FEED_RETRACT))
            pass

        if config['do_layer']:
            h_dots, v_dots = self.svg.size()

            self.send("5. Move pen to start of the part bin")
            self.send("6. Ink the layer")

            surface = self.svg.surface(layer)
            stride = surface.get_stride()
            image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
            image = numpy.reshape(image, (v_dots, stride))
            image = numpy.greater(image, 0)
            # Make into a 2-bit representation
            image = numpy.repeat(image, 2, axis=-1)
            image = numpy.packbits(image, axis=-1)

            # Got to the top margin
            self.send_escp(b'v', struct.pack("<L", self.margin_top))

            # Render the lines...
            lines = 180
            last_y = 0
            for y in range(0, v_dots//lines):
                # .. in groups of 180
                if y > 0:
                    self.send_escp(b'v', struct.pack("<L", lines))
                raster = [bytearray(image[y*lines + l]) for l in range(0, lines)]

                self._render_lines(raster, microweave = True)
                last_y = y*(lines + 1)
                pass

            lines = v_dots - last_y
            raster = [bytearray(image[last_y]) for l in range(0, lines)]
            self.send(code = b'\x0c')
            pass

        self.send("7. Retract recoating blade to start of the Feed Bin")

        if config['do_extrude']:
            self.send("8. The Feed Bin and Part bin raises by %.3fmm" % FEED_RETRACT)
            pass
        pass

    def finish(self):
        self.send_esc(b'@')
        self.send_esc(b'@')
        self.send_escp(b'R', b'\000' + b'REMOTE1')
        self.send_remote1(b'LD')
        self.send_remote1(b'JE', b'\000')
        self.send_esc(b'\000', b'\000\000')
        pass

#  vim: set shiftwidth=4 expandtab: # 
