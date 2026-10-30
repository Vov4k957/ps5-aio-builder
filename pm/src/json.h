#ifndef PM_JSON_H
#define PM_JSON_H
#include <stddef.h>
typedef struct { int type, start, end, next, children; } JToken;
typedef struct { char *text; JToken *t; int count, cap; size_t len, pos; } Json;
/* A document owns its input on success; caller retains it on failure. */
int json_parse(Json *j, char *text);
void json_free(Json *j);
int json_get(const Json *j, int object, const char *key);
int json_string(const Json *j, int token, char *out, size_t size);
int json_eq(const Json *j, int token, const char *value);
int json_bool(const Json *j, int token, int *out);
int json_int(const Json *j, int token, int *out);
#endif
