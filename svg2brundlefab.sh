#!/bin/sh

SVG_DIR="$1"

Z="0"
Z_SLICE="0.50"
X_MIN=-195
X_MAX=180

if [ -z "${SVG_DIR}" -o ! -d "${SVG_DIR}" ]; then
	echo "Usage: $0 /path/to/svg/files"
	exit 1
fi

cat <<EOF
; Print ${SVG_DIR} to the BrundleFab
G28 ; Home all axes
G91 ; Absolute positioning
M226 ; Wait for manual fill operation
G92 ; Reset zeros after fill operation
EOF

for d in `ls ${SVG_DIR}/*.svg | sort`; do
	convert -border 10 $d pbm:- | ./pbm2brundlefab
	Z=`echo ${Z} ${Z_SLICE} + p | dc`
	cat <<EOF
; Perform layer operations
T0 ; Select no tool
G0 Y0 ; Reset ink head
G0 X${X_MAX} ; Finish the layer deposition
G0 Z${Z} ; Drop the build layer
T20 ; Select heat lamp tool
G1 X0 Y0 ; Dry the layer
T0 ; Select no tool
G1 X${X_MIN} Y0 ; Move to feed start
G1 E${Z} ; Extrude a feed layer
G1 X0 Y0 ; Move to print start
; Print as we feed powder
EOF
done
