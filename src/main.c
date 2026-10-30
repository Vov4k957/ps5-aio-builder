/* PS5 AIO: send embedded ELF images to a running loader at localhost:9021.
 * The console does not download anything from the Internet.
 */
#include "payloads.h"
#include <arpa/inet.h>
#include <errno.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/socket.h>
#include <unistd.h>

#define ELF_LOADER_PORT 9021
#define CONNECT_ATTEMPTS 30
#define CONNECT_RETRY_MS 100
#define SEND_CHUNK (64u * 1024u)

static void delay_ms(unsigned int milliseconds) {
    while (milliseconds >= 1000u) {
        sleep(1);
        milliseconds -= 1000u;
    }
    if (milliseconds) usleep(milliseconds * 1000u);
}

static int send_payload(const aio_payload_t *item) {
    struct sockaddr_in target = {0};
    int sock = -1;
    const unsigned char *cursor = item->start;
    size_t remaining = (size_t)(item->end - item->start);
    int attempt;

    target.sin_family = AF_INET;
    target.sin_port = htons(ELF_LOADER_PORT);
    if (inet_pton(AF_INET, "127.0.0.1", &target.sin_addr) != 1) {
        fprintf(stderr, "[aio] Cannot parse loopback address\n");
        return -1;
    }
    for (attempt = 0; attempt < CONNECT_ATTEMPTS; attempt++) {
        sock = socket(AF_INET, SOCK_STREAM, 0);
        if (sock < 0) break;
        if (connect(sock, (const struct sockaddr *)&target, sizeof(target)) == 0) break;
        close(sock);
        sock = -1;
        delay_ms(CONNECT_RETRY_MS);
    }
    if (sock < 0) {
        fprintf(stderr, "[aio] Cannot connect to loader for %s (errno=%d)\n", item->name, errno);
        return -1;
    }
    while (remaining > 0) {
        size_t to_send = remaining < SEND_CHUNK ? remaining : SEND_CHUNK;
        ssize_t sent = send(sock, cursor, to_send, 0);
        if (sent <= 0) {
            fprintf(stderr, "[aio] Failed sending %s (errno=%d)\n", item->name, errno);
            close(sock);
            return -1;
        }
        cursor += sent;
        remaining -= (size_t)sent;
    }
    shutdown(sock, SHUT_WR);
    close(sock);
    printf("[aio] Sent: %s\n", item->name);
    return 0;
}

int main(void) {
    size_t i;
    printf("[aio] Starting %zu embedded payload(s)\n", aio_payload_count);
    for (i = 0; i < aio_payload_count; i++) {
        const aio_payload_t *p = &aio_payloads[i];
        printf("[aio] %zu/%zu %s (%zu bytes)\n", i + 1, aio_payload_count,
               p->name, (size_t)(p->end - p->start));
        if (send_payload(p) != 0) {
            fprintf(stderr, "[aio] Aborting after failure; later payloads not sent\n");
            return 1;
        }
        if (i + 1 < aio_payload_count) delay_ms(p->delay_ms);
    }
    puts("[aio] All payloads sent to elfldr");
    return 0;
}
