#!/bin/sh

SVG_DIR="$1"

Z="0.35"
Z_SLICE="0.50"
X_MIN=-195
X_MAX=180

SPREAD_FEED=3000
INK_FEED=4000
DRY_FEED=5000
POWDER_FEED=4500

if [ -z "${SVG_DIR}" -o ! -d "${SVG_DIR}" ]; then
	echo "Usage: $0 /path/to/svg/files"
	exit 1
fi

cat <<EOF
; Print ${SVG_DIR} to the BrundleFab
G28 X0 Y0 Z0 E0 ; Home all axes
G90 ; Absolute positioning
M226 ; Wait for manual fill operation
G92 ; Reset zeros after fill operation
T1 S30000 ; Ink spray rate (dots/minute)
T0 ; Select no tool
EOF

# density of 354? Don't know why, but that's what it takes
# for ImageMagik to make # a 96DPI image of a repsnapper SVG
#
DENSITY=354
for d in `ls ${SVG_DIR}/*.svg | sort`; do
	convert -border 0 -density ${DENSITY} $d pbm:- | ./pbm2brundlefab
	Z=`echo ${Z} ${Z_SLICE} + p | dc`
	cat <<EOF
; Perform layer operations
T0 ; Select no tool
G0 Y0 ; Reset ink head position
G1 X${X_MAX} F${SPREAD_FEED} ; Finish the layer deposition
G0 Z${Z}; Drop the build layer
T20 ; Select heat lamp tool
G1 X0 ${DRY_FEED}; Dry the layer
T0 ; Select no tool
G0 X${X_MIN} Y0 ; Move to feed start
G1 E${Z} F${POWDER_FEED}; Extrude a feed layer
G1 X0 Y0 F${SPREAD_FEED}; Move to print start
; Print as we feed powder
EOF
done
