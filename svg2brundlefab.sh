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
G21 ; Units are mm
G90 ; Absolute positioning
M117 Prepare
M1 ; Let the use make sure we're ready to home axes
G28 X0 Y0 ; Home print axes
M117 Fill powder
M0 ; Wait for manual fill operation
M117 ; Clear status message
T1 S3 ; Ink spray rate (dots/minute)
T0 ; Select no tool
EOF

# density of 377 = 96dpi / 0.254 in to mm
#
DENSITY=377
TMP=/tmp/foo.png
for d in `ls ${SVG_DIR}/*.svg | sort`; do
	inkscape -z -d ${DENSITY} $d -e ${TMP} >/dev/null || exit 1
	pngtopnm -alpha ${TMP} | pgmtopbm | pnminvert | ./pbm2brundlefab
	cat <<EOF
; Perform layer operations
T0 ; Select no tool
G0 Y0 ; Reset ink head position
G1 X${X_MAX} F${SPREAD_FEED} ; Finish the layer deposition
G91 ; Relative positioning
G0 Z${Z_SLICE}; Drop the build layer
G90 ; Absolute positioning
T20 ; Select heat lamp tool
G1 X0 ${DRY_FEED}; Dry the layer
T0 ; Select no tool
G0 X${X_MIN} Y0 ; Move to feed start
G91 ; Relative positioning
G1 E${Z_SLICE} F${POWDER_FEED}; Extrude a feed layer
G90 ; Absolute positioning
G1 X0 Y0 F${SPREAD_FEED}; Move to print start
; Print as we feed powder
EOF
done
