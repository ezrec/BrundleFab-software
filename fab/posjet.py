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

import fab
import numpy
import struct

FEED_RETRACT = 2.0 # mm

class Fab(fab.Fab):
    def send(self, comment, code = None):
        super(Fab, self).send(code = code)
        log = self.log

        # Custom override for printing the log file
        if log is not None:
            if comment is not None:
                log.write(b"# " + comment.encode() + b"\n")
            if code is not None:
                log.write(b"\\%03o" % (ord(code[0])))
                if code[0] == b'\033':
                    log.write(b"%c" % (ord(code[1])))
                    code = code[1:]
                for b in code[1:]:
                    log.write(b"\\x%02x" % (ord(b)))
                    pass
                pass
                log.write(b"\n")
            pass
        pass

    def prepare(self, svg = None, name = None, config = None):
        super(Fab, self).prepare(svg = svg, name = name, config = config)

        self.send("Cancel any pending operations", b'\022');
        self.send("Initialize printer", b'\033@');
        pass

    def jetfab_rlebit(self, line):
        out = bytearray([1])

        prev = None
        index = 0
        for byte in line:
            for bit in range(0, 8):
                val = (byte >> (7-bit)) & 1
                if index == 0:
                    prev = val
                elif val != prev or index == 127:
                    out += bytearray([(prev << 7) | index])
                    prev = val
                    index = 0
                
                index += 1
                pass
            pass

        if index > 0:
            out += bytearray([(prev << 7) | index])

        return out

    def jetfab_rlebyte(self, line):
        out = bytearray([8])

        prev = None
        index = 0
        for byte in line:
            if index == 0:
                prev = byte
            elif byte != prev or index == 255:
                out += bytearray([index, prev])
                prev = byte
                index = 0
                pass

            index += 1
            pass

        if index > 0:
            out += bytearray([index, prev])

        return out

    def jetfab_diff(self, line, prev):
        out = bytearray([254])

        for i in range(0, min(len(line), len(prev))):
            if line[i] != prev[i]:
                out += bytearray([i, line[i]])
                pass
            pass

        if len(line) < len(prev):
            for i in range(len(line), len(prev)):
                out += bytearray([i, 0xff])
                pass
            pass
        elif len(line) > len(prev):
            for i in range(len(prev), len(line)):
                out += bytearray([i, line[i]])
                pass
            pass

        return out

    def jetfab_line(self, y, x_dots, line, prev):
        if len(line) > 254:
            line = line[0:255]
        if len(prev) > 254:
            prev = prev[0:255]
        if line == prev:
            data = bytes(bytearray([255]))
        else:
            data_r0 = bytearray([0]) + line
            data_r1 = self.jetfab_rlebit(line)
            data_r8 = self.jetfab_rlebyte(line)
            data_rd = self.jetfab_diff(line, prev)
            length, data = min([
                            (len(data_r0), data_r0),
                            (len(data_r1), data_r1),
                            (len(data_r8), data_r8),
                            (len(data_rd), data_rd)])
            data = bytes(data)
            pass

        self.send("Line %d" % (y), b'\033h' + struct.pack("BB", 7, len(data)) + data)
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
            self.send("5. Move pen to start of the part bin")
            self.send("6. Ink the layer")
            w_dots, h_dots = self.svg.size()
            surface = self.svg.surface(layer)

            self.send("Generate %dx%d layer" % (w_dots, h_dots), None)
            self.send("Enter Horizontal Graphics Mode, 104x96 DPI", b'\033*\012\000\000')

            lastb = bytearray([0] * w_dots)
            stride = surface.get_stride()
            image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
            image = numpy.reshape(image, (h_dots, stride))
            image = numpy.equal(image, 0)
            image = numpy.packbits(image, axis=-1)

            y = 0
            for y in range(0, h_dots):
                outb = bytearray(image[y])
                self.jetfab_line(y, w_dots, outb, lastb)
                lastb = outb
                pass

            self.send("Layer complete", b"\012") # Form Feed
            pass

        self.send("7. Retract recoating blade to start of the Feed Bin")

        if config['do_extrude']:
            self.send("8. The Feed Bin and Part bin raises by %.3fmm" % FEED_RETRACT)
            pass
        pass


#  vim: set shiftwidth=4 expandtab: # 
