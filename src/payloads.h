#ifndef PS5_AIO_PAYLOADS_H
#define PS5_AIO_PAYLOADS_H

#include <stddef.h>
#include <stdint.h>

typedef struct {
    const char *name;
    const unsigned char *start;
    const unsigned char *end;
    unsigned int delay_ms;
} aio_payload_t;

extern const aio_payload_t aio_payloads[];
extern const size_t aio_payload_count;

#endif
