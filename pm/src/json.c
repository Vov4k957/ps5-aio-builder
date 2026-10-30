/* Small bounded JSON reader. No external dependencies or writable shared state. */
#include "json.h"
#include <ctype.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static void space(Json *j) {
    while (j->pos < j->len && strchr(" \t\r\n", j->text[j->pos])) j->pos++;
}
static int add(Json *j, int type) {
    if (j->count == j->cap) {
        int n = j->cap ? j->cap * 2 : 256;
        if (n > 262144) return -1;
        JToken *p = realloc(j->t, (size_t)n * sizeof(*p));
        if (!p) return -1;
        j->t = p; j->cap = n;
    }
    int i = j->count++;
    j->t[i] = (JToken){type, (int)j->pos, 0, 0, 0};
    return i;
}
static int value(Json *j, int depth) {
    space(j);
    if (j->pos >= j->len || depth > 32) return -1;
    char c = j->text[j->pos];
    int i = add(j, c);
    if (i < 0) return -1;
    if (c == '{' || c == '[') {
        char end = c == '{' ? '}' : ']';
        j->pos++; space(j);
        if (j->pos < j->len && j->text[j->pos] == end) j->pos++;
        else for (;;) {
            space(j);
            if (c == '{') {
                if (j->pos >= j->len || j->text[j->pos] != '"' || value(j, depth+1)<0) return -1;
                j->t[i].children++;
                space(j);
                if (j->pos >= j->len || j->text[j->pos++] != ':') return -1;
            }
            if (value(j, depth+1)<0) return -1;
            j->t[i].children++;
            space(j);
            if (j->pos >= j->len) return -1;
            char sep = j->text[j->pos++];
            if (sep == end) break;
            if (sep != ',') return -1;
        }
    } else if (c == '"') {
        j->pos++;
        for (;;) {
            if (j->pos >= j->len) return -1;
            unsigned char b = (unsigned char)j->text[j->pos++];
            if (b == '"') break;
            if (b < 32) return -1;
            if (b == '\\') {
                if (j->pos >= j->len) return -1;
                char e = j->text[j->pos++];
                if (e == 'u') {
                    for (int k=0;k<4;k++) if (j->pos >= j->len || !isxdigit((unsigned char)j->text[j->pos++])) return -1;
                } else if (!strchr("\"\\/bfnrt", e)) return -1;
            }
        }
    } else if (c == 't' || c == 'f' || c == 'n') {
        const char *s = c == 't' ? "true" : c == 'f' ? "false" : "null";
        size_t n = strlen(s);
        if (j->len-j->pos < n || memcmp(j->text+j->pos,s,n)) return -1;
        j->pos += n;
    } else {
        j->t[i].type = '0';
        if (c == '-') j->pos++;
        if (j->pos >= j->len || !isdigit((unsigned char)j->text[j->pos])) return -1;
        if (j->text[j->pos] == '0') j->pos++;
        else while (j->pos < j->len && isdigit((unsigned char)j->text[j->pos])) j->pos++;
        if (j->pos < j->len && j->text[j->pos] == '.') {
            j->pos++; size_t start = j->pos;
            while (j->pos < j->len && isdigit((unsigned char)j->text[j->pos])) j->pos++;
            if (j->pos == start) return -1;
        }
        if (j->pos < j->len && strchr("eE", j->text[j->pos])) {
            j->pos++;
            if (j->pos < j->len && strchr("+-",j->text[j->pos])) j->pos++;
            size_t start = j->pos;
            while (j->pos < j->len && isdigit((unsigned char)j->text[j->pos])) j->pos++;
            if (j->pos == start) return -1;
        }
    }
    j->t[i].end = (int)j->pos; j->t[i].next = j->count;
    return i;
}
int json_parse(Json *j, char *text) {
    *j = (Json){.text=text,.len=strlen(text)};
    if (j->len > 16u*1024*1024 || value(j,0)<0) goto fail;
    space(j);
    if (j->pos != j->len) goto fail;
    return 0;
fail:
    free(j->t); *j = (Json){0}; return -1;
}
void json_free(Json *j) { free(j->t); free(j->text); *j = (Json){0}; }
static unsigned hex4(const char *p) {
    unsigned n=0;
    for(int k=0;k<4;k++) { unsigned c=(unsigned char)p[k]; n=(n<<4) | (c<='9'?c-'0':(c|32)-'a'+10); }
    return n;
}
int json_string(const Json *j,int t,char *out,size_t cap) {
    if (!cap) return -1;
    out[0]=0;
    if(t<0||t>=j->count||j->t[t].type!='"') return -1;
    size_t w=0; int end=j->t[t].end-1;
    for(int p=j->t[t].start+1;p<end;p++) {
        unsigned c=(unsigned char)j->text[p];
        if(c=='\\') {
            c=(unsigned char)j->text[++p];
            if(c=='u') {
                c=hex4(j->text+p+1);p+=4;
                if(c>=0xd800&&c<=0xdbff) {
                    if(p+6>=end||j->text[p+1]!='\\'||j->text[p+2]!='u') return -1;
                    unsigned low=hex4(j->text+p+3);
                    if(low<0xdc00||low>0xdfff) return -1;
                    c=0x10000+((c-0xd800)<<10)+(low-0xdc00);p+=6;
                } else if(c>=0xdc00&&c<=0xdfff) return -1;
                if(!c) return -1;
                unsigned char b[4];int n;
                if(c<128){b[0]=(unsigned char)c;n=1;}
                else if(c<2048){b[0]=0xc0|(c>>6);b[1]=0x80|(c&63);n=2;}
                else if(c<65536){b[0]=0xe0|(c>>12);b[1]=0x80|((c>>6)&63);b[2]=0x80|(c&63);n=3;}
                else{b[0]=0xf0|(c>>18);b[1]=0x80|((c>>12)&63);b[2]=0x80|((c>>6)&63);b[3]=0x80|(c&63);n=4;}
                if(w+(size_t)n>=cap) return -1;
                memcpy(out+w,b,(size_t)n);w+=(size_t)n;continue;
            }
            const char *esc="bfnrt",*decoded="\b\f\n\r\t";
            const char *match=strchr(esc,(int)c);
            if(match)c=(unsigned char)decoded[match-esc];
        }
        if(w+1>=cap)return -1;
        out[w++]=(char)c;
    }
    out[w]=0;return 0;
}
int json_eq(const Json *j,int t,const char *s) {
    char buf[2048];return !json_string(j,t,buf,sizeof(buf))&&!strcmp(buf,s);
}
int json_get(const Json *j,int obj,const char *key) {
    if(obj<0||obj>=j->count||j->t[obj].type!='{')return -1;
    int found=-1;
    for(int k=obj+1;k<j->t[obj].next;) {
        int v=k+1;
        if(json_eq(j,k,key)){if(found!=-1)return -2;found=v;}
        k=j->t[v].next;
    }
    return found;
}
int json_bool(const Json *j,int t,int *out) {
    if(t<0||t>=j->count||(j->t[t].type!='t'&&j->t[t].type!='f'))return -1;
    *out=j->t[t].type=='t';return 0;
}
int json_int(const Json *j,int t,int *out) {
    if(t<0||t>=j->count||j->t[t].type!='0')return -1;
    errno=0;char *end;long n=strtol(j->text+j->t[t].start,&end,10);
    if(errno||end!=j->text+j->t[t].end||n<INT_MIN||n>INT_MAX)return -1;
    *out=(int)n;return 0;
}
