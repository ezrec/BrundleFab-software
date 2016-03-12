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
DPI_Y = 360
FEED_RETRACT = 2.0 # mm

BED_X = 40.0
BED_Y = 40.0
BED_Z = 40.0

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
        self.send_remote1(b'JH', struct.pack(">BL", 1, 0x1f000000) + b'\x32\x02\x86\x08\x00\x61')
        self.send_esc(b'\000', b'\000\000')

        self.send_escp(b'd', b'\000' * 32767)
        self.send_escp(b'd', b'\000' * 32767)
        self.send_esc(b'\001', b'@EJL 1284.4\n@EJL     \n')


        self.send_escp(b'R', b'\000REMOTE1')
        self.send_remote1(b'EX', struct.pack(">LB", 5, 0)) # ???
        self.send_remote1(b'AC', b'\x00') # ???
        self.send_esc(b'\000', b'\000\000')

        # Enable graphics mode
        self.send_escp(b'G', b'\001')

        # Set resolution
        svg.resolution(dpi = (DPI_X/2, DPI_Y/4))
        dots_h, dots_v = svg.size()
        unit = 1440
        page = unit / DPI_Y
        vertical = unit / DPI_Y
        horizontal = unit / DPI_X
        self.send_escp(b'U', struct.pack("<BBBH", page, vertical, horizontal, unit))

        # Set paper loading/ejection
        self.send_esc(b'\x19', struct.pack("<B", 1))
        # Set page length
        self.send_escp(b'C', struct.pack("<L", dots_v))
        # Set page top & bottom
        self.send_escp(b'c', struct.pack("<LL", 0, dots_v))
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

            print("svg.size", self.svg.size(), file = sys.stderr)
            surface = self.svg.surface(layer)
            stride = surface.get_stride()
            image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
            image = numpy.reshape(image, (v_dots, stride))
            image = numpy.greater(image, 0)
            # Make into a 2-bit representation
            image = numpy.repeat(image, 2, axis=-1)
            image = numpy.packbits(image, axis=-1)

            # Set veritical offset
            self.send_escp(b'v', struct.pack("<L", 0))
            # Render the lines...
            bwidth = len(image[0])
            cmode = 0  # Uncompressed
            bpp = 2 # 2 bits/pixel
            lines = 90
            for y in range(0, v_dots//lines):
                # .. in groups of 90
                raster = [bytearray(image[y*lines + l]) for l in range(0, lines)]
                raster = bytearray([]).join(raster)
                for color in [2, 1, 4]:
                    cmd = struct.pack("<BBBHH", color, cmode, bpp, bwidth, lines )
                    self.send_esc(b'i', cmd + raster)
                    self.send_escp(b'$', struct.pack("<L", 0))
                    cmd = struct.pack("<BBBHH", color | 0x40, cmode, bpp, bwidth, lines )
                    self.send_esc(b'i', cmd + raster)
                    self.send(code = b'\r')
                    pass
                self.send_escp(b'v', struct.pack("<L", DPI_Y))
                pass
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
