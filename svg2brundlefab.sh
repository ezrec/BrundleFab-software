#!/bin/sh

SVG_DIR="$1"

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
	cat <<EOF
; Perform layer operations
T0 ; Select no tool
G90 ; Relative positioning
G0 Z1 ; Drop the build layer
G91 ; Absolute positioning
T2 ; Select heat lamp tool
G0 X0 Y0 ; Dry the layer
T2 ; Select no tool
G0 X-150 Y0 ; Move to feed start
G90 ; Relative positioning
G0 E1 ; Extrude a feed layer
G91 ; Absolute positioning
G0 X0 Y0 ; Move to print start
; Print as we feed powder
EOF
done
