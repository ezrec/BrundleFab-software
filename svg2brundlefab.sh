#!/bin/sh

cat <<EOF
; Print to the BrundleFab
G28 ; Home all axes
G91 ; Absolute positioning
M226 ; Wait for manual fill operation
G92 ; Reset zeros after fill operation
EOF

for d in `ls *.svg | sort`; do
	bn=`basename $d .svg`
	convert -border 10 $d $bn.pbm
	./pbm2gcode <$bn.pbm
done
