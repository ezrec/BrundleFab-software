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
import struct

FEED_RETRACT = 2.0 # mm

class Fab(fab.Fab):
    def size_mm(self):
        return (200.0, 200.0, 200.0)

    def prepare(self, svg = None, name = None, config = None):
        super(Fab, self).prepare(svg = svg, name = name, config = config)

        # Do any start-of-day initialization here
        self.send("Initialize printer", b'\012\034');
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

            # Ink you layer her
            pass

        self.send("7. Retract recoating blade to start of the Feed Bin")

        if config['do_extrude']:
            self.send("8. The Feed Bin and Part bin raises by %.3fmm" % FEED_RETRACT)
            pass
        pass

    # Perform any end-of-day processing here
    def finish(self):
        self.send("Eject part")
        pass

#  vim: set shiftwidth=4 expandtab: # 
