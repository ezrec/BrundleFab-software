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

import sys
import numpy
import fab

from fab import in2mm, mm2in

X_BIN_FEED=0        # Start of the feed bin
X_BIN_PART=198      # Start of the part bin
X_BIN_WASTE=385     # Start of the waste bin

X_OFFSET_RECOAT=0   # Offset of the recoater blade
X_OFFSET_FUSER=45   # Offset of midpoint of fuser
X_OFFSET_THERM=95   # Offset of midpoint of thermal sensor
X_OFFSET_PEN=195    # Offset of the pen

FEED_RETRACT=2.0    # E retraction, in mm
FEED_SPREAD=3000    # Spread rate while depositing the layer
FEED_POWDER=4500    # Extruder feed rate (mm/minute)
FEED_FUSER_WARM=200 # Fuser pass rate during warm-up (mm/minute)
TIME_FUSER_WARM=6   # Time (in seconds) for fuser to complete its warm-up
FEED_FUSER_HOT=700  # Fuser pass rate during hot (mm/minute)
FEED_PEN=5000       # Pen movement (mm/minute)
X_DPI=96.0
Y_DPI=96.0

Y_DOTS=12

class Fab(fab.Fab):
    def gc(self, comment, code = None):
        if code is not None:
            code = code.encode() + b"\n"
        self.send(comment = comment, code = code)
        pass

    def prepare(self, svg = None, name = "Unknown", config = {}):
        self.config = config
        self.svg = svg

        layers = svg.layers()
        max_z_mm = svg.z_mm(layers)

        svg.resolution(dpi_h = X_DPI, dpi_v = Y_DPI)
        self.w_dots, self.h_dots = svg.size(mm_h = config['x_bound_mm'], mm_v = config['y_bound_mm'])
        svg.offset(mm_h = config['x_shift_mm'], mm_v = config['y_shift_mm'])

        self.gc("Print %s to the BrundleFab, %dmm, %d layers" % (name, max_z_mm, layers))
        self.gc("Units are mm", "G21")
        self.gc("Absolute positioning", "G90")
        self.gc("Set pen base offset", "G10 L1 P0 X%.3f" % (X_OFFSET_PEN))
        self.gc("Set black tool offset", "G10 L1 P1 X%.3f" % (X_OFFSET_PEN))
        self.gc("Set fuser tool offset", "G10 L1 P20 X%.3f" % (X_OFFSET_FUSER))
        self.gc("Set repowder blade offset", "G10 L1 P21 X%.3f" % (X_OFFSET_RECOAT))
        self.gc("Set thermal monitor tool offset", "G10 L1 P22 X%.3f" % (X_OFFSET_THERM))
        self.gc("Ink spray rate (sprays/dot)", "T1 S%d" % (config['sprays']))
        self.gc("Re-home the ink head", "G28 Y0")

        if config['do_startup']:
            self.gc(None, "M117 Ready to home")
            self.gc("Let the user make sure we're ready to home axes", "M0")
            self.gc("Home print axes", "G28 X0 Y0 E0")
            self.gc("NOTE: Z is _not_ homed, as it may be part of a multi-file print")

            self.gc(None, "M117 Prep Part")
            self.gc("Select the recoater tool", "T21")
            self.gc("Wait for Z prep", "M0")
            self.gc("Move to start of the Waste Bin", "G0 X%.3f" % (X_BIN_WASTE))

            self.gc(None, "M117 Levelling")
            self.gc("Move to start of the Part Bin", "G1 X%.3f F%.3f" % (X_BIN_PART, FEED_SPREAD))
            self.gc(None, "M117 Feed %dmm" % (int(max_z_mm)+5))
            self.gc("Wait for manual fill operation", "M0")
            self.gc("Clear status message", "M117")

        self.gc("Select repowder tool", "T21")
        self.gc("Move to feed start", "G1 X%.3f" % (X_BIN_FEED))

    def finish(self):
        self.last_z = None
        self.svg = None
        pass

    def brundle_line(self, x_dots, w_dots, toolmask, weave=True):
        origin = None
        for i in range(0, w_dots):
            if toolmask[i] != 0:
                origin = i
                break
        if origin == None:
            return

        self.gc(None, "T0")
        self.gc(None, "T1 P0")
        self.gc(None, "G1 X%.3f F%.3f" % (X_BIN_PART + in2mm(x_dots / X_DPI), FEED_PEN))
        self.gc(None, "G1 Y%.3f" % (in2mm(origin / Y_DPI)))

        for i in range(origin+1, w_dots):
            if (toolmask[origin] != toolmask[i]) or (i == w_dots - 1):
                if (i == w_dots - 1) and (toolmask[origin] == 0):
                    break
                self.gc(None, "T1 P%d" % (toolmask[origin]))
                self.gc(None, "G1 Y%.3f" % (in2mm((i - 1) / Y_DPI)))
                origin = i

        # Switching to tool 0 will cause a forward flush of the
        # inkbar, and the ink head will end up at the end of the
        # line.
        self.gc(None, "T0")

        # For interweave support, we retract X by a half-dot, and
        # cover the dots inbetween the forward pass on the
        # reverse pass
        if weave:
            self.gc(None, "G1 X%.3f F%.3f" % (X_BIN_PART + in2mm((x_dots - 0.5) / X_DPI), FEED_PEN))

        # Switch back to T1 to ink on the reverse movement of
        # then inkbar
        self.gc(None, "T1 P0")
        self.gc(None, "G0 Y0")
        pass

    def render(self, layer = 0):
        config = self.config

        z_delta_mm = self.svg.height_mm(layer)
        # Extrude a bit more than the layer width
        e_delta_mm = z_delta_mm * 1.1;

        self.gc(None, "M117 Slice %d of %d" % (layer+1, self.layers()))
        self.gc("1. Assume layer head is at feed start")
        self.gc(  "Select recoat tool", "T21")

        if config['do_extrude']:
            self.gc("2. Raise Feed Bin by one layer width")
            self.gc(  "Relative positioning", "G91")
            self.gc(  "Extrude a feed layer", "G1 E%.3f F%d" % (e_delta_mm, FEED_POWDER))
            self.gc(  "Absolute positioning", "G90")

            self.gc("3. Advance recoat blade past Waste Bin")
            self.gc(  "Advance to waste bin", "G1 X%.3f F%d" % (X_BIN_WASTE+15, FEED_SPREAD))
            self.gc("4. Drop Part Bin by %.3fmm, and Feed Bin by %.3fmm" % (FEED_RETRACT, FEED_RETRACT))
            self.gc(  "Relative positioning", "G91")
            self.gc(  "Drop bins to get out of the way", "G1 E%.3f Z%.3f F%d" % (-FEED_RETRACT, FEED_RETRACT, FEED_POWDER))
            self.gc(  "Absolute positioning", "G90")

        if config['do_layer']:
            self.gc("5. Move pen to start of the part bin")
            self.gc(  "Select ink tool", "T1 P0")
            self.gc(  "Move pen to end of the part bin", "G0 X%.3f" % (X_BIN_PART))
            self.gc("6. Ink the layer")
            # See brundle_layer()

        # Ink the layer
        w_dots = self.w_dots
        h_dots = self.h_dots
        weave = self.config['do_weave']

        surface = self.svg.surface(layer)
        stride = surface.get_stride()
        image = numpy.frombuffer(surface.get_data(), dtype=numpy.uint8)
        image = numpy.reshape(image, (h_dots, stride))
        image = numpy.greater(image, 0)

        for y in range(0, h_dots):
            l = y % Y_DOTS

            if l == 0:
                toolmask = numpy.zeros((stride))
                pass

            toolmask = toolmask + image[y]*(1 << l)

            if l == (Y_DOTS-1):
                self.brundle_line(y, w_dots, toolmask, weave)
                pass

            pass

        if y % Y_DOTS != 0:
            self.brundle_line(y, w_dots, toolmask, weave)

        # Finish the layer
        if config['do_fuser']:
            self.gc("7. Select fuser, and advance to Waste Bin start")
            self.gc(  "Select fuser, but unlit", "T20 P0 Q0")
            x_warm_delta_mm = FEED_FUSER_WARM * TIME_FUSER_WARM / 60
            self.gc(  "Advance to Waste Bin start + warm up", "G0 X%.3f" % (X_BIN_WASTE + x_warm_delta_mm+50))
            self.gc("8. The fuser is enabled, and brought up to temp")
            self.gc(  "Select fuser and temp", "T20 P%.3f Q%.3f" % (config['fuser_temp']+5, config['fuser_temp']-5))

            self.gc("9. Retract fuser to start of Part Bin")
            self.gc(  "Fuser warm-up", "G1 X%.3f F%d" % (X_BIN_WASTE+50, FEED_FUSER_WARM))
            for delta in range(0, int(X_BIN_WASTE - X_BIN_PART)/10):
                self.gc(  "Fuse ..", "G1 X%.3f F%d" % (X_BIN_WASTE - delta*10, FEED_FUSER_HOT))
            self.gc(  "Fuse ..", "G1 X%.3f F%d" % (X_BIN_PART, FEED_FUSER_HOT))
            self.gc("10. The fuser is disabled", "T20 P0 Q0")

        self.gc("11. Retract recoating blade to start of the Feed Bin")
        self.gc(  "Select the recoating tool", "T21")
        self.gc(  "Move to start", "G0 X%.3f Y0" % (X_BIN_FEED))

        if config['do_extrude']:
            self.gc("12. The Feed Bin and Part bin raises by %.3fmm" % FEED_RETRACT)
            self.gc(  "Relative positioning", "G91")
            self.gc(  "Raise the bins", "G1 E%.3f Z%.3f F%d" % (FEED_RETRACT, z_delta_mm - FEED_RETRACT, FEED_POWDER))
            self.gc(  "Absolute positioning", "G90")

#  vim: set shiftwidth=4 expandtab: # 
