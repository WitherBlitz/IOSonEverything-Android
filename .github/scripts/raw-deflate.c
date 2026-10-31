#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "zlib.h"

/* Match Python zlib.compressobj(6, Z_DEFLATED, -15), followed by flush(). */
int main(void) {
    size_t size = 0, capacity = 65536;
    unsigned char *input = malloc(capacity);
    if (!input) return 1;
    for (;;) {
        if (size == capacity) {
            capacity *= 2;
            void *next = realloc(input, capacity);
            if (!next) return 2;
            input = next;
        }
        size_t got = fread(input + size, 1, capacity - size, stdin);
        size += got;
        if (!got) break;
    }
    if (ferror(stdin) || size > 0xffffffffu) return 3;
    z_stream stream;
    memset(&stream, 0, sizeof(stream));
    if (deflateInit2(&stream, 6, Z_DEFLATED, -15, 8, Z_DEFAULT_STRATEGY) != Z_OK) return 4;
    size_t bound = deflateBound(&stream, (uLong)size) + 64;
    unsigned char *output = malloc(bound);
    if (!output || bound > 0xffffffffu) return 5;
    stream.next_in = input;
    stream.avail_in = (uInt)size;
    stream.next_out = output;
    stream.avail_out = (uInt)bound;
    int result = deflate(&stream, Z_NO_FLUSH);
    if ((result != Z_OK && result != Z_BUF_ERROR) || stream.avail_in) return 6;
    if (deflate(&stream, Z_FINISH) != Z_STREAM_END) return 7;
    size_t length = stream.total_out;
    deflateEnd(&stream);
    if (fwrite(output, 1, length, stdout) != length) return 8;
    free(output);
    free(input);
    return 0;
}
