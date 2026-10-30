#ifndef PM_HTTP_H
#define PM_HTTP_H
#include <stddef.h>
typedef struct { int status, sent; char *body; } Http;
long long clock_ms(void);
void pause_ms(int ms);
int http_call(int port,const char *method,const char *path,const char *body,int timeout_ms,Http *out);
void http_free(Http *r);
int url_encode(const char *s,char *out,size_t cap);
#endif
