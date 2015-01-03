/*
 * Copyright (C) 2015, Jason S. McMullan
 * All right reserved.
 * Author: Jason S. McMullan <jason.mcmullan@gmail.com>
 *
 * This program is free software; you can redistribute it and/or
 * modify it under the terms of the GNU General Public License
 * as published by the Free Software Foundation; either version 2
 * of the License, or (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 */

#include <stdint.h>
#include <stdio.h>
#include <malloc.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>

#define MM_PER_ROW     3.15f
            
void emit_pbm(FILE *out, uint8_t *pbm, int line, int width)
{
    int i;

    fprintf(out, "; ");
    for (i = 0; i < width; i++) {
        fprintf(out, "%02X", pbm[i]);
    }
    fprintf(out, "\n");
}

uint8_t base64_of(int var)
{
    var &= 0x3f;

    if (var < 26)
        return var + 'A';
    else if (var < 52)
        return (var - 26) + 'a';
    else if (var < 62)
        return (var - 52) + '0';
    else if (var == 62)
        return '+';
    else
        return '/';
}

void base64_emit(FILE *out, const uint8_t *byte, int bytes)
{
    uint16_t buff = 0;
    int i, bit = 0;

    for (i = 0; i < bytes; i++) {
        buff <<= 8;
        buff |= byte[i];
        bit += 8;
        while (bit >= 6) {
            fprintf(out, "%c", base64_of(buff >> (bit - 6)));
            bit -= 6;
        }
    }

    if (bit == 2) {
        fprintf(out, "%c", base64_of(buff << 4));
        fprintf(out, "==");
    } else if (bit == 4) {
        fprintf(out, "%c", base64_of(buff << 2));
        fprintf(out, "=");
    }

    fprintf(out, "\n");
}

void emit_toolmask(FILE *out, uint16_t *toolmask, int toolbits, int line, int width)
{
    int toolbytes = width * ((toolbits + 7) / 8);
    int i, len;
    float mm_per_col = MM_PER_ROW / toolbits;
    uint8_t buff[toolbytes];

    fprintf(out, "G0 X0 Y%f ; Line %d\n", (line / toolbits) * MM_PER_ROW, line);
    fprintf(out, "T1 P%f S%d ; Pattern\n", width * mm_per_col, toolbytes);
    for (i = len = 0; i < width; i++) {
        if (toolbits > 8)
            buff[len++] = (toolmask[i] >> 8) & 0xff;
        buff[len++] = toolmask[i] & 0xff;
    }
    base64_emit(out, buff, len);
    fprintf(out, "\n");
    fprintf(out, "G0 X%f ; Spray pattern\n", width * mm_per_col);
}

int main(int argc, char **argv)
{
    FILE *in = stdin;
    FILE *out = stdout;
    int type, x, y;
    int stride;
    int rc, i;
    uint8_t *pbm;
    uint16_t *toolmask;
    int toolbits = 12;  /* 12-jet ink sprayer */

    /* Read PBM header */
    rc = fscanf(in, "P%d\n%d %d\n", &type, &x, &y);
    if (rc != 3 || type != 4) {
        fprintf(stderr, "%s: Input is not a PBM\n", argv[0]);
        return EXIT_FAILURE;
    }

    stride = (x + 7) / 8;
    pbm = malloc(stride);
fprintf(stderr, "Stride = %d\n", stride);
    toolmask = malloc(sizeof(toolmask[0]) * x);

    /* Convert bitstream into toolmask */
    for (i = 0; i < y; i++) {
        int j, bit;
        rc = fread(pbm, sizeof(uint8_t), stride, in);
        if (rc != stride) {
            fprintf(stderr, "%s: Input error: %s\n", argv[0], strerror(errno));
            return EXIT_FAILURE;
        }
        emit_pbm(out, pbm, i, stride);
        bit = i % toolbits;
        for (j = 0; j < x; j++) {
            uint8_t c = pbm[j>>3];
            if (c & (1 << (7 - (j & 7))))
                toolmask[j] |= (1 << bit);
        }
        if (bit == (toolbits - 1)) {
            emit_toolmask(out, toolmask, toolbits, i, x);
            memset(toolmask, 0, sizeof(toolmask[0]) * x);
        }
    }

    if ((i % toolbits) != (toolbits - 1))
        emit_toolmask(out, toolmask, toolbits, i, x);

    fclose(in);
    fclose(out);
    return EXIT_SUCCESS;
}

/* vim: set shiftwidth=4 expandtab:  */
